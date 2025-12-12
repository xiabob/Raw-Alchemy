# -*- coding: utf-8 -*-
"""
Adobe XMP Profile Generator (Fixed to match XMPconverter.cpp)

Features:
1. Color Space Transform (Linear ProPhoto -> Target Log -> User LUT).
2. Tetrahedral Interpolation for high-quality resizing.
3. Adobe RGBTable Binary Format (Delta Encoded, Zlib Compressed, Base85).
4. Full range amount slider (0-200%).

Dependencies: pip install colour-science numpy
"""

import hashlib
import struct
import uuid
import zlib
from io import BytesIO

import numpy as np
import colour

# Handle optional dependencies for standalone usage
try:
    from .constants import LOG_ENCODING_MAP, LOG_TO_WORKING_SPACE
except ImportError:
    # Dummy maps if running standalone for testing
    LOG_ENCODING_MAP = {}
    LOG_TO_WORKING_SPACE = {}

# --- Constants ---

# Adobe Custom Base85 Characters (Standard Adobe Order)
# C++ Source: kEncodeTable
ADOBE_Z85_CHARS = b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#"
ADOBE_Z85_TABLE = [chr(c) for c in ADOBE_Z85_CHARS]

# --- Helper Functions ---

def int_round(n):
    """Matches C++ int_round: integer rounding of float."""
    return np.floor(n + 0.5).astype(np.int32)

def adobe_base85_encode(data: bytes) -> str:
    """
    Encodes binary data into Adobe's custom Base85 format.
    Matches XMPconverter.cpp logic: Little-Endian reading, LSB-first char output.
    """
    length = len(data)
    encoded_chars = []
    
    # Process 4-byte chunks
    for i in range(0, length, 4):
        chunk = data[i : i + 4]
        chunk_len = len(chunk)
        
        # C++ logic pads the reading buffer with 0s if we are at the end
        if chunk_len < 4:
            chunk = chunk + b'\x00' * (4 - chunk_len)
        
        # Unpack as Little-Endian Unsigned Int (<I)
        # C++: x = *(sPtr_1_ + i);
        val = struct.unpack('<I', chunk)[0]
        
        # Calculate Base85 characters
        # C++: Loop 5 times, output = table[x % 85], x /= 85
        # Logic regarding padding:
        # C++ Loop: if (j > 0 && !--compressedSize_1) break;
        # This means:
        # 1 byte input  -> 2 chars output
        # 2 bytes input -> 3 chars output
        # 3 bytes input -> 4 chars output
        # 4 bytes input -> 5 chars output
        
        chars_to_write = 5
        if i + 4 > length:
            remaining = length - i
            chars_to_write = remaining + 1

        for j in range(5):
            if j < chars_to_write:
                encoded_chars.append(ADOBE_Z85_TABLE[val % 85])
            val //= 85

    return "".join(encoded_chars)


def apply_cst_pipeline(user_lut_path, log_space, output_size=33, _log=print):
    """
    Loads user LUT, creates ProPhoto Identity, transforms to Log, applies LUT.
    Returns: (output_size, final_data_numpy)
    """
    _log(f"Processing: Reading {user_lut_path}...")
    user_lut = colour.read_LUT(user_lut_path)
    
    # --- FIX START ---
    # 1. Create Identity Grid in Linear ProPhoto RGB
    # 修正：使用 (R, G, B) 顺序。Axis 0 是 R，Axis 2 是 B。
    # 这符合 colour-science 和 .cube 文件的标准顺序。
    domain = np.linspace(0, 1, output_size)
    R, G, B = np.meshgrid(domain, domain, domain, indexing='ij')
    
    # 堆叠为 (R, G, B, 3) 形状
    prophoto_linear = np.stack([R, G, B], axis=-1) 
    # --- FIX END ---
    
    log_color_space_name = LOG_TO_WORKING_SPACE.get(log_space)
    log_curve_name = LOG_ENCODING_MAP.get(log_space, log_space)

    _log(f"  - Pipeline: ProPhoto Linear -> {log_color_space_name} -> {log_curve_name} -> LUT")
        
    # A. Gamut Transform: ProPhoto RGB -> Target Gamut (Linear)
    matrix = colour.matrix_RGB_to_RGB(
        colour.RGB_COLOURSPACES['ProPhoto RGB'],
        colour.RGB_COLOURSPACES[log_color_space_name]
    )
    # 矩阵乘法 (Numpy array 是行向量，所以乘转置矩阵)
    target_gamut_linear = prophoto_linear @ matrix.T
    target_gamut_linear = np.maximum(target_gamut_linear, 1e-7)

    # B. Transfer Function: Linear -> Log
    log_encoded = colour.cctf_encoding(target_gamut_linear, function=log_curve_name)
        
    # C. Apply User LUT
    # 由于现在的 grid 结构是 (R,G,B)，与 standard LUT 结构一致，插值结果也会保持正确的空间顺序
    _log(f"  - Applying User LUT ({user_lut.size}^3) to grid...")
    final_rgb = user_lut.apply(log_encoded, interpolator=colour.algebra.table_interpolation_tetrahedral)
    
    # --- Debug Feature ---
    try:
        debug_filename = f"debug_pipeline_{output_size}.cube"
        _log(f"  [DEBUG] Writing pipeline output to {debug_filename}...")
        # 此时 final_rgb 已经是标准的 (R, G, B, 3) 顺序，可以直接写入
        debug_lut = colour.LUT3D(table=final_rgb, name=f"Debug Pipeline {log_space}")
        colour.write_LUT(debug_lut, debug_filename)
        _log(f"  [DEBUG] Successfully wrote {debug_filename}")
    except Exception as e:
        _log(f"  [DEBUG] Failed to write debug cube: {e}")

    return output_size, final_rgb

def generate_rgb_table_stream(data, size, min_amt=0, max_amt=200):
    """
    Encodes the numpy data into DNG RGBTable binary format.
    Input data shape MUST be: (R, G, B, 3)
    """
    stream = BytesIO()
    
    # Helpers for writing Little Endian
    def write_u32(val): stream.write(struct.pack('<I', val))
    def write_double(val): stream.write(struct.pack('<d', val))
    
    # --- 1. Header (16 bytes) ---
    write_u32(1)    # format: btt_RGBTable
    write_u32(1)    # version
    write_u32(3)    # dimensions (3D)
    write_u32(size) # divisions (N)
    
    # --- 2. Data Processing (Deltas) ---
    
    # Clip and Scale to 0-65535
    data = np.clip(data, 0.0, 1.0)
    data_scaled = int_round(data * 65535) # Shape (R, G, B, 3)
    
    # Generate Identity Curve
    indices = np.arange(size, dtype=np.int32)
    nop_curve = (indices * 0xFFFF + (size >> 1)) // (size - 1)
    
    # Create Identity Grid (R, G, B order)
    # indexing='ij' ensures (Axis0=R, Axis1=G, Axis2=B)
    grid_r, grid_g, grid_b = np.meshgrid(nop_curve, nop_curve, nop_curve, indexing='ij')
    
    # Calculate Deltas (Actual - Identity)
    # Result is int32, potentially negative
    delta_r = data_scaled[..., 0] - grid_r
    delta_g = data_scaled[..., 1] - grid_g
    delta_b = data_scaled[..., 2] - grid_b
    
    # Interleave data: R, G, B, R, G, B...
    # Stack along last axis -> (R, G, B, 3)
    deltas_stacked = np.stack((delta_r, delta_g, delta_b), axis=-1)
    
    # Flatten: C-order (Row Major) matches the C++ loop nesting of r(inner), g, b(outer)
    flat_deltas = deltas_stacked.flatten()
    
    # Cast to uint16 (Little Endian)
    # This automatically handles the "Delta" logic.
    # e.g., -1 becomes 65535 (0xFFFF) in 2's complement, which is what 'H' or '<u2' expects for raw bits
    stream.write(flat_deltas.astype('<u2').tobytes())
        
    # --- 3. Footer Integers (12 bytes) ---
    # C++ Default: Adobe (1, 3), ProPhoto (2, 2), sRGB (0, 1)
    # Based on XMPconverter.cpp logic
    colors = 2
    gamma = 2

    write_u32(colors) # colors
    write_u32(gamma)  # gamma
    write_u32(0)      # gamut (0=clip, 1=extend) - defaulting to 0 as per typical use
    
    # --- 4. Footer Range (16 bytes) ---
    write_double(min_amt * 0.01)
    write_double(max_amt * 0.01)
    
    return stream.getvalue()

def create_xmp_profile(profile_name, lut_path, log_space=None, _log=print):
    """
    Main function to generate the XMP string.
    """
    profile_uuid = str(uuid.uuid4()).replace('-', '').upper()

    # 1. Pipeline (Keep your existing logic here)
    # Assuming apply_cst_pipeline returns (size, data) where data is (R,G,B,3)
    size, data = apply_cst_pipeline(lut_path, log_space, output_size=32, _log=_log)
    
    # 2. Binary Encoding (Uncompressed)
    # Note: Usually ProPhoto is the working space for profiles
    raw_bytes = generate_rgb_table_stream(data, size, min_amt=0, max_amt=200)
    
    # 3. Fingerprinting (MD5 of uncompressed binary)
    m = hashlib.md5()
    m.update(raw_bytes)
    fingerprint = m.hexdigest().upper()
    
    # 4. Compression (Zlib with Length Prefix)
    # Matches C++: memcpy(dPtr_1, &uncompressedSize_1, 4);
    uncompressed_len = len(raw_bytes)
    header = struct.pack('<I', uncompressed_len)
    
    # Matches C++: compress2(...)
    compressed_payload = zlib.compress(raw_bytes, level=zlib.Z_BEST_COMPRESSION)
    
    full_binary_blob = header + compressed_payload
    
    # 5. Ascii85 Encoding
    encoded_data = adobe_base85_encode(full_binary_blob)
    
    # 6. XMP Template Assembly
    xmp_template = f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00        ">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:PresetType="Look"
   crs:Cluster=""
   crs:UUID="{profile_uuid}"
   crs:SupportsAmount="True"
   crs:SupportsColor="True"
   crs:SupportsMonochrome="True"
   crs:SupportsHighDynamicRange="True"
   crs:SupportsNormalDynamicRange="True"
   crs:SupportsSceneReferred="True"
   crs:SupportsOutputReferred="True"
   crs:RequiresRGBTables="False"
   crs:ShowInPresets="True"
   crs:ShowInQuickActions="False"
   crs:CameraModelRestriction=""
   crs:Copyright=""
   crs:ContactInfo=""
   crs:Version="14.3"
   crs:ProcessVersion="11.0"
   crs:ConvertToGrayscale="False"
   crs:RGBTable="{fingerprint}"
   crs:Table_{fingerprint}="{encoded_data}"
   crs:HasSettings="True">
   <crs:Name>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{profile_name}</rdf:li>
    </rdf:Alt>
   </crs:Name>
   <crs:Group>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">Profiles</rdf:li>
    </rdf:Alt>
   </crs:Group>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""
    return xmp_template
