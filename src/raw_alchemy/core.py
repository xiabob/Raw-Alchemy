import rawpy
import numpy as np
import colour
import tifffile
from typing import Optional

# 1. 映射：Log 空间名称 -> 对应的线性色域 (Linear Gamut)
LOG_TO_WORKING_SPACE = {
    'F-Log': 'F-Gamut',
    'F-Log2': 'F-Gamut',
    'F-Log2C': 'F-Gamut C',
    'V-Log': 'V-Gamut',
    'N-Log': 'N-Gamut',
    'Canon Log 2': 'Cinema Gamut',
    'Canon Log 3': 'Cinema Gamut',
    'S-Log3': 'S-Gamut3',
    'S-Log3.Cine': 'S-Gamut3.Cine',
    'LogC3': 'ARRI Wide Gamut 3',
    'LogC4': 'ARRI Wide Gamut 4',
    'Log3G10': 'RED Wide Gamut RGB',
}

# 2. 映射：复合名称 -> colour 库识别的 Log 编码函数名称
# 例如：S-Log3.Cine 使用的是 S-Gamut3.Cine 色域，但曲线依然是 S-Log3
LOG_ENCODING_MAP = {
    'S-Log3.Cine': 'S-Log3',
    'F-Log2C': 'F-Log2',
    # 其他名称如果跟 colour 库一致，可以在代码逻辑中直接 fallback
}

# 3. 映射：用户友好的 LUT 空间名 -> colour 库标准名称
LUT_SPACE_MAP = {
    "Rec.709": "ITU-R BT.709",
    "Rec.2020": "ITU-R BT.2020",
}

def _calculate_middle_gray_correction(luminance_data: np.ndarray, max_stops: float = 4.0) -> float:
    """
    计算将图像平均亮度对齐到 18% 中性灰所需的增益系数。
    包含安全限制 (Clamping)，防止夜景照片爆白。
    """
    # 使用 mean 可能受极值影响，也可以考虑 np.median
    mean_luminance = np.mean(luminance_data)
    
    if mean_luminance > 1e-6:
        middle_gray_target = 0.18
        correction = middle_gray_target / mean_luminance
        
        # 安全限制：最大提亮倍数 (例如 4 stops = 16x)
        max_gain = 2 ** max_stops
        if correction > max_gain:
            print(f"  ! Warning: Calculated gain {correction:.2f} exceeds limit. Clamping to {max_gain} ({max_stops} stops).")
            return float(max_gain)
        
        print(f"  - Scene mean luminance: {mean_luminance:.4f}. Calculated multiplier: {correction:.2f}")
        return float(correction)
    
    print("  - Scene is essentially black, skipping middle gray correction.")
    return 1.0


def process_image(
    raw_path: str,
    output_path: str,
    log_space: str,
    lut_path: Optional[str],
    lut_space: Optional[str],
    matrix_method: str = "metadata",
    exposure: Optional[float] = None,
):
    """
    RAW Alchemy 核心管线：RAW -> Linear ACES -> Target Log -> LUT -> Adobe RGB TIFF
    """
    print(f"Processing: {raw_path}")
    print("Step 1: Determining exposure and Linearization...")
    
    with rawpy.imread(raw_path) as raw:  # type: ignore
        # --- 3-Tier Exposure Logic ---
        exposure_source = "middle_gray" # Default fallback
        brightness_multiplier = 1.0

        if exposure is not None:
            # 1. Manual Override (手动指定)
            exposure_source = "manual"
            print(f"  - Using manual exposure override of {exposure:.2f} stops.")
            brightness_multiplier = 2**exposure
        else:
            # 2. BaselineExposure (尝试读取 DNG/元数据中的基准曝光)
            try:
                # 注意：rawpy 并不总是能读到 baseline_exposure，取决于相机和库版本
                if hasattr(raw, 'baseline_exposure') and raw.baseline_exposure is not None:
                    # 有些时候这个值可能是 0，需要判断
                    if raw.baseline_exposure != 0:
                        baseline_exposure = raw.baseline_exposure
                        exposure_source = "baseline"
                        print(f"  - Using BaselineExposure of {baseline_exposure:.2f} stops.")
                        brightness_multiplier = 2**baseline_exposure
            except Exception:
                pass # Fallback if attribute missing
        
        print(f"Step 2: Converting RAW to ACES AP0 (Linear) using '{matrix_method}' matrix...")
        
        if matrix_method == "metadata":
            # 路径 A: 使用相机内置矩阵 -> XYZ -> ACES
            # 关键：no_auto_bright=True 保证得到原始线性数据
            xyz_image = raw.postprocess(
                gamma=(1, 1),
                no_auto_bright=True,
                use_camera_wb=True,
                output_bps=16,
                output_color=rawpy.ColorSpace.XYZ,  # type: ignore
                bright=brightness_multiplier, # 在解拜耳阶段应用增益，画质最好
            )
            # 归一化到 0.0 - 1.0
            xyz_image_float = xyz_image.astype(np.float32) / 65535.0

            if exposure_source == "middle_gray":
                print("  - No BaselineExposure or Manual set. Applying auto middle gray correction.")
                # XYZ 的 Y 通道即亮度
                luminance = xyz_image_float[..., 1]
                correction = _calculate_middle_gray_correction(luminance)
                xyz_image_float *= correction

            # XYZ (D65) -> ACES AP0 (Linear)
            # colour 库会自动处理矩阵变换
            ap0_linear = colour.XYZ_to_RGB(
                xyz_image_float,
                colour.CCS_ILLUMINANTS["CIE 1931 2 Degree Standard Observer"]["D65"],
                colour.RGB_COLOURSPACES["aces2065-1"].whitepoint,
                colour.RGB_COLOURSPACES["aces2065-1"].matrix_XYZ_to_RGB,
            )

        elif matrix_method == "adobe":
            # 路径 B: 使用 Adobe 矩阵 (通过转 Adobe RGB Linear) -> ACES
            adobe_rgb_linear = raw.postprocess(
                gamma=(1, 1),
                no_auto_bright=True,
                use_camera_wb=True,
                output_bps=16,
                output_color=rawpy.ColorSpace.Adobe,  # type: ignore
                bright=brightness_multiplier,
            )
            adobe_rgb_float = adobe_rgb_linear.astype(np.float32) / 65535.0

            if exposure_source == "middle_gray":
                print("  - No BaselineExposure tag. Applying auto middle gray correction.")
                # 需先转 XYZ 才能算亮度
                xyz_temp = colour.RGB_to_XYZ(
                    adobe_rgb_float,
                    colour.RGB_COLOURSPACES['Adobe RGB (1998)'].whitepoint,
                    colour.RGB_COLOURSPACES['Adobe RGB (1998)'].whitepoint,
                    colour.RGB_COLOURSPACES['Adobe RGB (1998)'].matrix_RGB_to_XYZ,
                )
                luminance = xyz_temp[..., 1]
                correction = _calculate_middle_gray_correction(luminance)
                adobe_rgb_float *= correction

            # Adobe RGB (Linear) -> ACES AP0 (Linear)
            # 这一步 colour 库会处理色度适应 (Bradford) 因为白点可能略有不同
            ap0_linear = colour.RGB_to_RGB(
                adobe_rgb_float,
                colour.RGB_COLOURSPACES["Adobe RGB (1998)"],
                colour.RGB_COLOURSPACES["aces2065-1"],
            )
        else:
            raise ValueError(f"Unknown matrix method: {matrix_method}")

    # Step 3: ACES AP0 (Linear) -> Target Log Space
    # 这一步是把巨大的 ACES 空间压缩进相机 Log 空间
    print(f"Step 3: Converting ACES AP0 to {log_space}...")
    
    working_space_name = LOG_TO_WORKING_SPACE.get(log_space)
    if not working_space_name:
        raise NotImplementedError(f"Log space '{log_space}' is not supported in mapping.")

    # 3.1 Gamut Mapping: ACES AP0 -> Camera Native Gamut (Linear)
    # 注意：这里我们不做 Tone Mapping，只是色彩空间的变换
    working_space_linear = colour.RGB_to_RGB(
        ap0_linear,
        colour.RGB_COLOURSPACES['aces2065-1'],
        colour.RGB_COLOURSPACES[working_space_name],
        chromatic_adaptation_transform='Bradford' # 显式指定，保证白点对齐
    )

    # 3.2 Log Encoding: Linear -> Log Curve
    # 获取正确的 Log 函数名 (处理 .Cine 等后缀情况)
    log_encoding_name = LOG_ENCODING_MAP.get(log_space, log_space)
    
    log_encoding_function = colour.LOG_ENCODINGS.get(log_encoding_name)
    if not log_encoding_function:
        raise NotImplementedError(f"Log encoding function for '{log_encoding_name}' not found in colour library.")
    
    log_image = log_encoding_function(working_space_linear)
    image_to_save = log_image # 默认保存 Log，除非下面应用了 LUT

    # Step 4: Apply LUT (if provided) and convert to Adobe RGB
    if lut_path and lut_space:
        print(f"Step 4: Applying LUT {lut_path}...")
        
        # 读取并应用 LUT
        # 注意：LUT 通常期望输入是 0-1 范围的 Log 信号
        lut = colour.read_LUT(lut_path)
        image_after_lut = lut.apply(log_image)
        
        print(f"Step 5: Converting from {lut_space} to Adobe RGB (Corrected Gamma Flow)...")
        colour_lut_space_name = LUT_SPACE_MAP.get(lut_space)
        if not colour_lut_space_name:
            raise ValueError(f"LUT space '{lut_space}' is not supported.")
            
        # --- 核心修正：Gamma Sandwich ---
        # 1. Input: LUT 输出 (通常是 Gamma 2.4/2.2) -> 必须解码为 Linear
        # 2. Transform: Linear Rec.709 -> Linear Adobe RGB
        # 3. Output: Linear Adobe RGB -> Encoded Adobe RGB (Gamma 2.2)
        final_image = colour.RGB_to_RGB(
            image_after_lut,
            input_colourspace=colour.RGB_COLOURSPACES[colour_lut_space_name],
            output_colourspace=colour.RGB_COLOURSPACES["Adobe RGB (1998)"],
            chromatic_adaptation_transform='Bradford',
            apply_cctf_decoding=True, # 解码输入 Gamma (例如 Rec.709 OETF)
            apply_cctf_encoding=True  # 编码输出 Gamma (Adobe RGB Gamma)
        )
        image_to_save = final_image
    else:
        print("  - No LUT provided. Output will be LOG encoded image.")

    # Step 6: Save final image as TIFF
    print(f"Step 6: Saving to {output_path}...")
    
    # Clipping 保护：防止溢出导致数值回绕
    image_clipped = np.clip(image_to_save, 0.0, 1.0)
    
    # 转换为 16-bit 整数
    image_16bit = (image_clipped * 65535).astype(np.uint16)
    
    # 写入 TIFF (不压缩，保证兼容性)
    tifffile.imwrite(output_path, image_16bit)
    print("Done!")
