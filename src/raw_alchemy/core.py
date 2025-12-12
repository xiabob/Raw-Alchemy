import gc
import rawpy
import numpy as np
import colour
import tifffile
from PIL import Image
import pillow_heif
import os
import time
from typing import Optional

from . import utils

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
    'Arri LogC3': 'ARRI Wide Gamut 3',
    'Arri LogC4': 'ARRI Wide Gamut 4',
    'Log3G10': 'REDWideGamutRGB',
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

# 4. 测光模式选项
METERING_MODES = [
    'average',        # 几何平均 (默认)
    'center-weighted',# 中央重点
    'highlight-safe', # 高光保护 (ETTR)
    'hybrid',         # 混合 (平均 + 高光限制)
]

def process_image(
    raw_path: str,
    output_path: str,
    log_space: str,
    lut_path: Optional[str],
    exposure: Optional[float] = None, # 如果是 None 则自动，如果是数字则手动
    lens_correct: bool = True,
    metering_mode: str = 'hybrid',
    custom_db_path: Optional[str] = None,
    log_queue: Optional[object] = None, # 用于多进程日志记录
):
    import os
    filename = os.path.basename(raw_path)

    # Simple timing helper (ms) to mirror Swift/bridge logs
    t_total = time.perf_counter()
    t_last = t_total
    def _t(label: str):
        nonlocal t_last
        now = time.perf_counter()
        print(f"[RawAlchemy][decode] {label}: {(now - t_last) * 1000:.2f} ms")
        t_last = now

    def _log(message):
        if log_queue:
            # 对于 GUI，发送结构化日志以避免混淆
            log_queue.put({'id': filename, 'msg': message})
        else:
            # 对于 CLI，直接打印
            print(message)

    _log(f"🧪 [Raw Alchemy] Processing: {raw_path}")

    # --- Step 1: 统一解码 (优化内存) ---
    _log(f"  🔹 [Step 1] Decoding RAW...")
    with rawpy.imread(raw_path) as raw:
        _t("open_file")
        # --- Step 1.1: 提取 EXIF ---
        # 在解码前提取，即使解码失败也能获取信息
        exif_data = utils.extract_lens_exif(raw, logger=_log)

        # --- Step 1.2: 解码 ---
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
        _t("postprocess")
        img = prophoto_linear.astype(np.float32) / 65535.0
        _t("convert_16u_to_float")
        del prophoto_linear # <--- 关键：立即释放巨大的 uint16 数组
        gc.collect()        # <--- 强制回收

    source_cs = colour.RGB_COLOURSPACES['ProPhoto RGB']

    # Debug: dump decoded ProPhoto linear (float32) before any processing
    debug_dump_decoded_prophoto_path = '/tmp/raw_alchemy_prophoto_float.bin'
    if debug_dump_decoded_prophoto_path:
        out = img.astype(np.float32, copy=False)
        out.tofile(debug_dump_decoded_prophoto_path)
        h, w, _ = out.shape
        _log(f"  🧪 [Debug] Dumped decoded ProPhoto float32 to {debug_dump_decoded_prophoto_path} (w={w}, h={h}, bytes={out.nbytes})")

    # --- Step 2: 曝光控制 (二选一) ---
    # 定义最终使用的增益 gain
    gain = 1.0

    if exposure is not None:
        # === 路径 A: 手动曝光 ===
        _log(f"  🔹 [Step 2] Manual Exposure Override ({exposure:+.2f} stops)")
        gain = 2.0 ** exposure
        
        # 应用增益
        utils.apply_gain_inplace(img, gain)

    else:
        # === 路径 B: 自动测光 ===
        _log(f"  🔹 [Step 2] Auto Exposure ({metering_mode})")
        
        # 为了复用 utils 里的函数 (假设它们返回的是处理后的图)，我们直接调用
        if metering_mode == 'center-weighted':
            img = utils.auto_expose_center_weighted(img, source_cs, target_gray=0.18, logger=_log)
        elif metering_mode == 'highlight-safe':
            img = utils.auto_expose_highlight_safe(img, clip_threshold=1.0, logger=_log)
        elif metering_mode == 'average':
            img = utils.auto_expose_linear(img, source_cs, target_gray=0.18, logger=_log)
        else:
            # 默认混合模式
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


    # 经验值：饱和度 1.15 ~ 1.25，对比度 1.0 ~ 1.1
    # 这会让你的 RAW 转换结果在过 LUT 之前就拥有足够的"底料"
    _log("  🔹 [Step 3.5] Applying Camera-Match Boost...")
    img = utils.apply_saturation_and_contrast(img, saturation=1.25, contrast=1.1)

    # --- Step 4: 转换色彩空间 (Linear -> Log) ---
    log_color_space_name = LOG_TO_WORKING_SPACE.get(log_space)
    log_curve_name = LOG_ENCODING_MAP.get(log_space, log_space)
    
    if not log_color_space_name:
         raise ValueError(f"Unknown Log Space: {log_space}")

    _log(f"  🔹 [Step 4] Color Transform (ProPhoto -> {log_color_space_name} -> {log_curve_name})")

    # 4.1 Gamut 变换
    M = colour.matrix_RGB_to_RGB(
        colour.RGB_COLOURSPACES['ProPhoto RGB'],
        colour.RGB_COLOURSPACES[log_color_space_name],
    )
    if not img.flags['C_CONTIGUOUS']:
        img = np.ascontiguousarray(img)
    utils.apply_matrix_inplace(img, M)
    # Log 编码前必须裁剪负值
    np.maximum(img, 1e-6, out=img)

    # Debug: dump pre-log (after matrix+clamp) if requested
    debug_dump_prelog_float_path = '/tmp/raw_alchemy_prelog_float.bin'
    if debug_dump_prelog_float_path:
        out = img.astype(np.float32, copy=False)
        out.tofile(debug_dump_prelog_float_path)
        h, w, _ = out.shape
        _log(f"  🧪 [Debug] Dumped pre-log RGB float32 to {debug_dump_prelog_float_path} (w={w}, h={h}, bytes={out.nbytes})")

    # 4.2 Curve 编码
    img = colour.cctf_encoding(img, function=log_curve_name)

    # 可选：导出 Log 编码后的 float32 buffer，便于与 Swift 端二进制对比
    debug_dump_log_float_path = '/tmp/raw_alchemy_log_float.bin'
    if debug_dump_log_float_path:
        if not img.flags['C_CONTIGUOUS']:
            img = np.ascontiguousarray(img)
        out = img.astype(np.float32, copy=False)
        out.tofile(debug_dump_log_float_path)
        h, w, _ = out.shape
        _log(f"  🧪 [Debug] Dumped log RGB float32 to {debug_dump_log_float_path} (w={w}, h={h}, bytes={out.nbytes})")

    # --- Step 5: LUT (Numba In-Place) ---
    if lut_path:
        _log(f"  🔹 [Step 5] Applying LUT {lut_path}...")
        try:
            lut = colour.read_LUT(lut_path)
            
            # 判断是否为标准的 3D LUT，如果是，则使用 Numba 加速
            if isinstance(lut, colour.LUT3D):
                # 必须确保输入内存连续，否则 Numba 可能会变慢或报错
                if not img.flags['C_CONTIGUOUS']:
                    img = np.ascontiguousarray(img)
                
                # 调用 Numba 核函数
                utils.apply_lut_inplace(
                    img, 
                    lut.table, 
                    lut.domain[0], 
                    lut.domain[1]
                )
            else:
                # 如果是 1D LUT 或 LUTSequence，回退到 colour 库自带方法
                _log("    (Using standard colour library for non-3D LUT)")
                img = lut.apply(img)

            # LUT 后防溢出
            np.clip(img, 0.0, 1.0, out=img)
            
        except Exception as e:
            _log(f"  ❌ [Error] applying LUT: {e}")
            import traceback
            traceback.print_exc()

    # --- Step 6: 保存 ---
    _log(f"  💾 Preparing to save to {output_path}...")
    
    file_ext = os.path.splitext(output_path)[1].lower()
    output_image_uint16 = None # Initialize

    try:
        if file_ext in ['.tif', '.tiff']:
            _log("    Format: TIFF (16-bit, ZLIB compression)")
            output_image_uint16 = (img * 65535).astype(np.uint16)
            tifffile.imwrite(
                output_path,
                output_image_uint16,
                photometric='rgb',
                compression='zlib' # <--- 启用压缩
            )
        elif file_ext in ['.heic', '.heif']:
            _log("    Format: HEIF (10-bit, Lossless)")
            output_image_uint16 = (img * 65535).astype(np.uint16)
            # 根据用户反馈，使用 pillow_heif.from_bytes 以获得更直接的控制
            heif_file = pillow_heif.from_bytes(
                mode='RGB;16',
                size=(output_image_uint16.shape[1], output_image_uint16.shape[0]),
                data=output_image_uint16.tobytes()
            )
            heif_file.save(output_path, quality=-1, bit_depth=10)
        else:
            # Fallback for common 8-bit formats like JPEG/PNG
            _log(f"    Format: {file_ext.upper()} (8-bit)")
            output_image_uint8 = (np.clip(img, 0.0, 1.0) * 255).astype(np.uint8)
            Image.fromarray(output_image_uint8).save(output_path)

        _log(f"  ✅ Successfully saved to {output_path}")

    except Exception as e:
        _log(f"  ❌ [Error] Failed to save file: {e}")
        import traceback
        traceback.print_exc()
    
    # 显式清理
    del img
    if output_image_uint16 is not None:
        del output_image_uint16
    gc.collect()
    _log("  ✅ Done.")
    print(f"[RawAlchemy][decode] total: {(time.perf_counter() - t_total) * 1000:.2f} ms")
