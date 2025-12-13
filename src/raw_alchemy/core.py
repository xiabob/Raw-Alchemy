import gc
import rawpy
import numpy as np
import colour
import tifffile
from PIL import Image
import pillow_heif
import os
from typing import Optional

# 尝试导入同级目录下的 utils，如果失败则尝试绝对导入 (方便不同运行环境调试)
try:
    from . import utils, xmp_generator
    from .constants import LOG_ENCODING_MAP, LOG_TO_WORKING_SPACE, METERING_MODES
except ImportError:
    from raw_alchemy import utils, xmp_generator
    from raw_alchemy.constants import LOG_ENCODING_MAP, LOG_TO_WORKING_SPACE, METERING_MODES

# ==========================================
#              2. 核心处理函数
# ==========================================

def _decode_and_prepare_raw(
    raw_path: str,
    exposure: Optional[float],
    metering_mode: str,
    lens_correct: bool,
    custom_db_path: Optional[str],
    _log: callable
):
    """
    Internal function to handle RAW decoding, exposure, and lens correction.
    This is the common base for all processing pipelines.
    Returns a float32 numpy array in ProPhoto RGB linear space.
    """
    _log(f"  🔹 [Step 1] Decoding RAW...")
    with rawpy.imread(raw_path) as raw:
        exif_data = utils.extract_lens_exif(raw, logger=_log)
        prophoto_linear = raw.postprocess(
            gamma=(1, 1),
            no_auto_bright=True,
            use_camera_wb=True,
            output_bps=16,
            output_color=rawpy.ColorSpace.ProPhoto,
            bright=1.0,
            highlight_mode=2,
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AAHD,
        )
        img = prophoto_linear.astype(np.float32) / 65535.0
        del prophoto_linear
        gc.collect()

    source_cs = colour.RGB_COLOURSPACES['ProPhoto RGB']

    # --- Step 2: 曝光控制 ---
    if exposure is not None:
        _log(f"  🔹 [Step 2] Manual Exposure Override ({exposure:+.2f} stops)")
        gain = 2.0 ** exposure
        utils.apply_gain_inplace(img, gain)
    else:
        _log(f"  🔹 [Step 2] Auto Exposure ({metering_mode})")
        if metering_mode == 'center-weighted':
            img = utils.auto_expose_center_weighted(img, source_cs, target_gray=0.18, logger=_log)
        elif metering_mode == 'highlight-safe':
            img = utils.auto_expose_highlight_safe(img, clip_threshold=1.0, logger=_log)
        elif metering_mode == 'average':
            img = utils.auto_expose_linear(img, source_cs, target_gray=0.18, logger=_log)
        elif metering_mode == 'matrix':
            img = utils.auto_expose_matrix(img, source_cs, target_gray=0.18, logger=_log)
        else: # hybrid as default
            img = utils.auto_expose_hybrid(img, source_cs, target_gray=0.18, logger=_log)

    # --- Step 3: 镜头校正 ---
    if lens_correct:
        _log("  🔹 [Step 3] Applying Lens Correction...")
        img = utils.apply_lens_correction(
            img,
            exif_data=exif_data,
            custom_db_path=custom_db_path,
            logger=_log
        )
    else:
        _log("  🔹 [Step 3] Skipping Lens Correction.")

    # 稍微增加饱和度和对比度，为 LUT 转换打底
    _log("  🔹 [Step 3.5] Applying Camera-Match Boost...")
    img = utils.apply_saturation_and_contrast(img, saturation=1.25, contrast=1.1)
    
    return img

def process_image(
    raw_path: str,
    output_path: str,
    log_space: str,
    lut_path: Optional[str],
    exposure: Optional[float] = None, # None=自动, Float=手动EV
    lens_correct: bool = True,
    metering_mode: str = 'hybrid',
    custom_db_path: Optional[str] = None,
    log_queue: Optional[object] = None, # 多进程通信队列
):
    filename = os.path.basename(raw_path)
    def _log(message):
        log_msg = {'id': filename, 'msg': message}
        if log_queue and hasattr(log_queue, 'put'):
            log_queue.put(log_msg)
        else:
            print(f"[{log_msg['id']}] {log_msg['msg']}")

    _log(f"🧪 [Full Process] Processing: {raw_path}")

    # --- Steps 1-3: Decode, Expose, Correct ---
    img = _decode_and_prepare_raw(
        raw_path, exposure, metering_mode, lens_correct, custom_db_path, _log
    )

    # --- Step 4: 色彩空间转换 (ProPhoto Linear -> Log) ---
    log_color_space_name = LOG_TO_WORKING_SPACE.get(log_space)
    log_curve_name = LOG_ENCODING_MAP.get(log_space, log_space)
    
    if not log_color_space_name:
         raise ValueError(f"Unknown Log Space: {log_space}")

    _log(f"  🔹 [Step 4] Color Transform (ProPhoto -> {log_color_space_name} -> {log_curve_name})")

    # 4.1 Gamut 变换 (矩阵运算)
    M = colour.matrix_RGB_to_RGB(
        colour.RGB_COLOURSPACES['ProPhoto RGB'],
        colour.RGB_COLOURSPACES[log_color_space_name],
    )
    if not img.flags['C_CONTIGUOUS']:
        img = np.ascontiguousarray(img)
    utils.apply_matrix_inplace(img, M)
    
    # 4.2 Log 编码
    # Log 函数无法处理负值，需裁剪微小底噪
    np.maximum(img, 1e-6, out=img) 
    img = colour.cctf_encoding(img, function=log_curve_name)

    # --- Step 5: 应用 LUT ---
    if lut_path:
        _log(f"  🔹 [Step 5] Applying LUT {os.path.basename(lut_path)}...")
        try:
            lut = colour.read_LUT(lut_path)
            
            # 3D LUT 使用 Numba 加速
            if isinstance(lut, colour.LUT3D):
                if not img.flags['C_CONTIGUOUS']:
                    img = np.ascontiguousarray(img)
                
                utils.apply_lut_inplace(img, lut.table, lut.domain[0], lut.domain[1])
            else:
                # 1D LUT 使用 colour 库默认方法
                img = lut.apply(img)

            # LUT 可能导致数值溢出，需裁剪到 [0.0, 1.0]
            np.clip(img, 0.0, 1.0, out=img)
            
        except Exception as e:
            _log(f"  ❌ [Error] applying LUT: {e}")

    # --- Step 6: 保存 (关键优化部分) ---
    _log(f"  💾 Saving to {os.path.basename(output_path)}...")
    
    file_ext = os.path.splitext(output_path)[1].lower()
    output_image_uint16 = None

    try:
        # === A. 16-bit TIFF (无损母版) ===
        if file_ext in ['.tif', '.tiff']:
            _log("    Format: TIFF (16-bit, ZLIB Optimized)")
            output_image_uint16 = (img * 65535).astype(np.uint16)
            
            tifffile.imwrite(
                output_path,
                output_image_uint16,
                photometric='rgb',
                compression='zlib',
                # 【优化】predictor=2 (水平差分) 大幅提升照片压缩率
                # predictor=2,       
                # 【优化】level=8 平衡速度和体积
                compressionargs={'level': 8} 
            )

        # === B. 10-bit HEIF (高质量分享) ===
        elif file_ext in ['.heic', '.heif']:
            _log("    Format: HEIF (10-bit, High Quality)")
            output_image_uint16 = (img * 65535).astype(np.uint16)
            
            # 使用 pillow_heif 直接写入
            heif_file = pillow_heif.from_bytes(
                mode='RGB;16',
                size=(output_image_uint16.shape[1], output_image_uint16.shape[0]),
                data=output_image_uint16.tobytes()
            )
            # 【优化】quality=-1 (无损/最高画质), bit_depth=10, 保持 4:4:4
            heif_file.save(output_path, quality=-1, bit_depth=10)

        # === C. 8-bit JPEG (通用预览) ===
        else:
            _log(f"    Format: {file_ext.upper()} (8-bit High Quality)")
            # 转换为 8-bit
            output_image_uint8 = (np.clip(img, 0.0, 1.0) * 255).astype(np.uint8)
            
            # 针对 JPG 的特殊优化参数
            save_params = {}
            if file_ext in ['.jpg', '.jpeg']:
                save_params = {
                    'quality': 95,
                    'subsampling': 0,
                    'optimize': True
                }
            
            Image.fromarray(output_image_uint8).save(output_path, **save_params)

        _log(f"  ✅ Saved: {output_path}")

    except Exception as e:
        _log(f"  ❌ [Error] Failed to save file: {e}")
        import traceback
        traceback.print_exc()
    
    # --- 最终清理 ---
    del img
    if output_image_uint16 is not None:
        del output_image_uint16
    gc.collect()


def generate_prophoto_tiff(
    raw_path: str,
    output_path: str, # Should be a .tif path
    exposure: Optional[float] = None,
    lens_correct: bool = True,
    metering_mode: str = 'hybrid',
    custom_db_path: Optional[str] = None,
    log_queue: Optional[object] = None,
):
    """
    Decodes a RAW file to a 16-bit linear ProPhoto RGB TIFF.
    This is a simplified pipeline for generating a "digital negative".
    """
    filename = os.path.basename(raw_path)
    def _log(message):
        log_msg = {'id': filename, 'msg': message}
        if log_queue and hasattr(log_queue, 'put'):
            log_queue.put(log_msg)
        else:
            print(f"[{log_msg['id']}] {log_msg['msg']}")

    _log(f"🧪 [ProPhoto TIFF] Generating for: {raw_path}")

    # --- Steps 1-3: Decode, Expose, Correct ---
    img = _decode_and_prepare_raw(
        raw_path, exposure, metering_mode, lens_correct, custom_db_path, _log
    )

    # --- Step 4: Save as 16-bit TIFF ---
    _log(f"  💾 Saving ProPhoto TIFF to {os.path.basename(output_path)}...")
    try:
        # Clip to [0, 1] range before converting to uint16
        np.clip(img, 0.0, 1.0, out=img)
        output_image_uint16 = (img * 65535).astype(np.uint16)
        
        tifffile.imwrite(
            output_path,
            output_image_uint16,
            photometric='rgb',
            compression='zlib',
            # predictor=2,
            compressionargs={'level': 8}
        )
        _log(f"  ✅ Saved: {output_path}")

    except Exception as e:
        _log(f"  ❌ [Error] Failed to save TIFF file: {e}")
        import traceback
        traceback.print_exc()
    finally:
        del img
        if 'output_image_uint16' in locals():
            del output_image_uint16
        gc.collect()


def process_with_xmp(
    raw_path: str,
    output_path: str, # Base path for .tif and .xmp
    log_space: str,
    lut_path: str,
    exposure: Optional[float] = None,
    lens_correct: bool = True,
    metering_mode: str = 'hybrid',
    custom_db_path: Optional[str] = None,
    log_queue: Optional[object] = None,
):
    """
    Generates a ProPhoto TIFF and a corresponding XMP sidecar file.
    """
    filename = os.path.basename(raw_path)
    def _log(message):
        log_msg = {'id': filename, 'msg': message}
        if log_queue and hasattr(log_queue, 'put'):
            log_queue.put(log_msg)
        else:
            print(f"[{log_msg['id']}] {log_msg['msg']}")

    # Define paths. The output_path is a base, e.g. /path/image (no ext)
    tiff_path = f"{output_path}.tif"
    xmp_path = f"{output_path}.xmp"
    
    # --- Step 1: Generate the ProPhoto TIFF ---
    _log("  ▶️  Generating ProPhoto TIFF as base...")
    # We can reuse the dedicated function for this
    generate_prophoto_tiff(
        raw_path=raw_path,
        output_path=tiff_path,
        exposure=exposure,
        lens_correct=lens_correct,
        metering_mode=metering_mode,
        custom_db_path=custom_db_path,
        log_queue=log_queue,
    )

    # --- Step 2: Generate and save the XMP profile ---
    if not lut_path:
        _log("  ⚠️ Skipping XMP generation: No LUT file provided.")
        return

    _log(f"  ▶️  Generating XMP Profile for {log_space}...")
    try:
        # The profile name should be user-friendly
        profile_name = f"RA - {log_space} - {os.path.basename(os.path.splitext(lut_path)[0])}"
        
        xmp_content = xmp_generator.create_xmp_profile(
            profile_name=profile_name,
            log_space=log_space,
            lut_path=lut_path,
            _log=_log
        )
        
        with open(xmp_path, 'w', encoding='utf-8') as f:
            f.write(xmp_content)
        
        _log(f"  ✅ Saved XMP Profile: {xmp_path}")

    except NameError:
        _log(f"  ❌ [Error] Failed to generate XMP: `xmp_generator` module not available.")
    except Exception as e:
        _log(f"  ❌ [Error] Failed to generate XMP profile: {e}")
        import traceback
        traceback.print_exc()