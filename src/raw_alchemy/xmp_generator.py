# -*- coding: utf-8 -*-
"""
Module for generating Adobe Camera Raw (ACR) XMP profiles.

This module is responsible for creating .xmp files that can be used as color profiles
in Adobe Lightroom and Photoshop (via ACR). The goal is to embed a color transformation
pipeline (ProPhoto RGB -> Target Log Space -> User LUT) into the profile.

Note: The structure of XMP profiles, especially those with embedded 3D LUTs (`LookTable`),
is complex and not fully documented publicly. The initial implementation provides a
template, and further research or reverse-engineering might be needed to achieve a
fully functional LUT embedding.
"""

import base64
import gzip
import os
import uuid

import colour as cs
import numpy as np
from colour.io.luts import LUT3D, read_LUT

try:
    from .constants import LOG_ENCODING_MAP, LOG_TO_WORKING_SPACE
except ImportError:
    from constants import LOG_ENCODING_MAP, LOG_TO_WORKING_SPACE


def generate_look_table_data(lut_path: str, log_space: str) -> str:
    """
    Generates the gzipped and Base64 encoded LookTable data with accurate CST.

    This is the core logic:
    1. Load the user's .cube LUT to determine its size.
    2. Create an identity LUT of the same size in ProPhoto RGB.
    3. **[CST] Convert gamut from ProPhoto to the target Log's working space (e.g., V-Gamut).**
    4. **[CST] Apply the Log transfer function (e.g., V-Log) to the gamut-converted LUT.**
    5. Apply the user's creative LUT to the fully transformed LUT.
    6. Convert the final float LUT to 16-bit unsigned integers.
    7. Gzip and Base64 encode the data.
    """
    # 1. Load the user's creative LUT to determine its size
    try:
        user_lut = read_LUT(lut_path)
        user_lut.table = user_lut.table.astype(np.float32)
        lut_size = user_lut.size
    except Exception as e:
        raise IOError(f"Failed to read or parse LUT file: {lut_path}") from e

    # 2. Create an identity LUT of the same size in ProPhoto linear.
    identity_lut = LUT3D.linear_table(lut_size)
    
    # 3. Perform Gamut Conversion (ProPhoto -> Target Gamut)
    target_gamut_name = LOG_TO_WORKING_SPACE.get(log_space)
    if not target_gamut_name:
        raise ValueError(f"No working space defined for log space: '{log_space}'")

    source_cs = cs.RGB_COLOURSPACES['ProPhoto RGB']
    target_cs = cs.RGB_COLOURSPACES.get(target_gamut_name)
    if not target_cs:
        raise ValueError(f"Unsupported or unknown gamut in colour-science: '{target_gamut_name}'")

    # Calculate and apply the conversion matrix
    matrix = cs.matrix_RGB_to_RGB(source_cs, target_cs)
    gamut_converted_table = cs.dot_vector(matrix, identity_lut.table)

    # 4. Get and apply the Log transfer function
    log_curve_name = LOG_ENCODING_MAP.get(log_space, log_space)
    log_cctf = cs.CCTF_ENCODINGS.get(log_curve_name)
    if not log_cctf:
        raise ValueError(
            f"Unsupported or unknown log curve: '{log_space}' (resolved to '{log_curve_name}')"
        )
    
    # Apply curve to the *gamut-converted* table
    log_encoded_lut_table = log_cctf(gamut_converted_table)

    # 5. Apply the user's LUT to the log-encoded LUT data
    final_lut_table = user_lut.apply(
        log_encoded_lut_table, interpolator=cs.interpolate.interp_trilinear
    )

    # 6. Clip, reorder channels to BGR, and convert to 16-bit unsigned integers
    final_lut_table = np.clip(final_lut_table, 0.0, 1.0)
    final_lut_table_bgr = final_lut_table[..., ::-1].copy()
    lut_data_uint16 = (final_lut_table_bgr * 65535).astype(np.uint16)

    # 7. Gzip and Base64 encode
    compressed_data = gzip.compress(lut_data_uint16.tobytes())
    encoded_data = base64.b64encode(compressed_data).decode("utf-8")

    return encoded_data


def create_xmp_profile(
    profile_name: str,
    log_space: str,
    lut_path: str,
) -> str:
    """
    Generates the XML content for an XMP color profile.

    This function creates an XMP profile that applies a specific look, which is
    intended to be the combination of a Log conversion and a LUT application.

    Args:
        profile_name: The display name for the profile in Lightroom/ACR.
        log_space: The target Log colorspace (e.g., 'S-Log3').
        lut_path: Path to the .cube LUT file.

    Returns:
        A string containing the full XML content for the .xmp file.
    """
    profile_uuid = str(uuid.uuid4())

    try:
        look_table_data = generate_look_table_data(lut_path, log_space)
    except (ValueError, IOError) as e:
        print(f"Error generating LookTable: {e}")
        look_table_data = ""  # Fallback to an empty LookTable on error

    xmp_template = f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 6.0-c001 79.164488, 2021/10/22-12:04:21        ">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    crs:Version="14.0"
    crs:ProcessVersion="11.0"
    crs:WhiteBalance="As Shot"
    crs:HasSettings="True">
   <dc:format>image/x-raw</dc:format>
   <crs:Look>
    <rdf:Description
     crs:Name="{profile_name}"
     crs:Amount="1.000000"
     crs:UUID="{profile_uuid.upper()}"
     crs:SupportsAmount="false"
     crs:SupportsMonochrome="false"
     crs:SupportsOutputReferred="false">
     <crs:Group>
      <rdf:Alt>
       <rdf:li xml:lang="x-default">Raw Alchemy</rdf:li>
      </rdf:Alt>
     </crs:Group>
     <crs:Parameters>
      <rdf:Description
       crs:Version="14.0"
       crs:ProcessVersion="11.0"
       crs:ConvertToGrayscale="False"
       crs:CameraProfile="Adobe Standard"
       crs:LookTable="{look_table_data}">
      </rdf:Description>
     </crs:Parameters>
    </rdf:Description>
   </crs:Look>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""
    return xmp_template
