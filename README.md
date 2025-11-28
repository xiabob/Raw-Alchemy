# Raw Alchemy

[简体中文](README_zh-CN.md)

---

A Python-based command-line tool for an advanced RAW image processing pipeline. It is designed to convert RAW files into a scene-referred linear format within the ACES (Academy Color Encoding System) framework, apply camera-specific log curves, and integrate creative LUTs for a complete and color-managed workflow.

### Core Concepts

Many photographers and videographers rely on creative LUTs (Look-Up Tables) to achieve specific visual styles. However, a common pain point arises: **applying a LUT that works perfectly in a video workflow to a RAW photo often results in incorrect colors.**

This issue stems from a color space mismatch. Most creative LUTs are designed for a specific Log color space (e.g., Sony's S-Log3/S-Gamut3.Cine or Fujifilm's F-Log2/F-Gamut). When you open a RAW photo in software like Photoshop or Lightroom and directly apply these LUTs, the default decoded color space of the RAW file does not match the LUT's expected input, leading to severe color and tonal shifts.

**Raw Alchemy** is designed to solve this exact problem. It builds a rigorous, automated color pipeline to ensure any LUT can be accurately applied to any RAW file:

1.  **Standardized Decoding to ACES**: The tool first decodes any RAW file into a standardized, ultra-wide gamut intermediate space—ACES AP0 (Linear). This neutralizes the inherent color science differences between camera brands, providing a consistent, device-independent starting point for all operations.
2.  **Precise Log Signal Preparation**: Next, it accurately transforms the image data from the ACES space into the precise Log format the target LUT expects, such as the `F-Log2` curve and `F-Gamut` color space. This step is crucial for color consistency, as it perfectly mimics the process of how a camera generates its Log video signal internally.
3.  **Correct LUT Application**: By applying your creative LUT to this precisely prepared Log image, the resulting color and tone will perfectly match its intended appearance in a professional video editing suite like DaVinci Resolve.
4.  **Color-Managed Output**: Finally, the LUT-processed image is safely transformed from the wide gamut space into the standard Adobe RGB (1998) space, generating a 16-bit TIFF file. This ensures the final result remains accurate for viewing on different devices and for printing.

Through this pipeline, `Raw Alchemy` bridges the gap between RAW photography and professional video color grading, empowering photographers with the same level of color management precision enjoyed in the world of cinema.

### Processing Pipeline

The tool follows these precise color transformation steps:

`RAW (Camera Native)` -> `ACES AP0 (Linear)` -> `Camera Gamut (Linear)` -> `Camera Log (e.g., F-Log2)` -> `(Optional) Creative LUT` -> `Adobe RGB (1998) TIFF`

### Features

-   **RAW to ACES**: Decodes RAW files directly into the ACES AP0 (Linear) working color space.
-   **Log Conversion**: Supports a wide range of camera-specific log formats (F-Log2, S-Log3, LogC4, etc.).
-   **LUT Application**: Applies `.cube` LUT files for creative color grading.
-   **Exposure Control**: Provides a 3-tier exposure logic: manual override, metadata-based `BaselineExposure`, or automatic middle-gray normalization.
-   **High-Quality Output**: Saves the final image as a 16-bit TIFF file in the Adobe RGB (1998) color space.
-   **Tech Stack**: Uses `rawpy` for RAW decoding and `colour-science` for high-precision color transformations.

### Installation

This project has critical dependencies with specific installation requirements. Please follow these steps carefully.

**Step 1: Install the `rawpy` fork**

`rawpy` has system-level dependencies that vary by OS. Please visit the required fork and follow the detailed installation instructions in its `README`:

➡️ **[https://github.com/shenmintao/rawpy.git](https://github.com/shenmintao/rawpy.git)**

Ensure you can successfully `import rawpy` in Python before proceeding.

**Step 2: Install `colour-science`**

Install the required development branch from GitHub:
```bash
pip install git+https://github.com/colour-science/colour.git@develop
```

**Step 3: Install Raw Alchemy**

Once the dependencies above are successfully installed, you can install this project.
```bash
# Clone this repository
git clone https://github.com/shenmintao/raw-alchemy.git
cd raw-alchemy

# Install the tool
pip install .
```

### Usage

The tool is operated via the `raw-alchemy` command.

#### Basic Syntax

```bash
raw-alchemy [OPTIONS] <INPUT_RAW_PATH> <OUTPUT_TIFF_PATH>
```

#### Example 1: Basic Log Conversion

This example converts a RAW file to ACES, applies the F-Log2 curve, and saves the result as an Adobe RGB TIFF file.

```bash
raw-alchemy "path/to/your/image.CR3" "path/to/output/image.tiff" --log-space "F-Log2"
```

#### Example 2: Conversion with a Creative LUT

This example converts a RAW file, applies the S-Log3 curve, then applies a creative LUT (`my_look.cube`), and saves the final result.

**Important**: When using a LUT, you must specify its output color space via `--lut-space`. This is typically `Rec.709` or `Rec.2020`.

```bash
raw-alchemy "input.ARW" "output.tiff" --log-space "S-Log3" --lut "looks/my_look.cube" --lut-space "Rec.709"
```

#### Example 3: Using the Adobe Matrix

This example forces the initial RAW decoding to use the Adobe coefficient matrix built into `rawpy` instead of relying on the file's metadata.

```bash
raw-alchemy "input.NEF" "output_adobe.tiff" --matrix-method "adobe"
```

#### Example 4: Manual Exposure Adjustment

This example manually applies a +1.5 stop exposure compensation, overriding any metadata or auto-exposure logic.

```bash
raw-alchemy "input.CR3" "output_bright.tiff" --exposure 1.5
```

### Command-Line Options

-   `<INPUT_RAW_PATH>`: (Required) Path to the input RAW file (e.g., .CR3, .ARW, .NEF).
-   `<OUTPUT_TIFF_PATH>`: (Required) Path to save the output 16-bit TIFF file.

-   `--log-space TEXT`: (Optional, Default: `F-Log2`) The target log color space.
-   `--matrix-method TEXT`: (Optional, Default: `metadata`) The matrix to use for the RAW to ACES conversion.
    -   `metadata`: Use the matrix from the camera file's metadata. This is usually the most accurate option.
    -   `adobe`: Force the use of the LibRaw built-in Adobe coefficient matrix.
-   `--exposure FLOAT`: (Optional) Manual exposure adjustment in stops (e.g., -0.5, 1.0). Overrides all auto-exposure logic.
-   `--lut TEXT`: (Optional) Path to a `.cube` LUT file to be applied after the log conversion.
-   `--lut-space TEXT`: (Required if `--lut` is used) The output color space of the LUT. Must be one of `Rec.709` or `Rec.2020`.

### Supported Log Spaces

The `--log-space` option supports the following values:
-   `F-Log`
-   `F-Log2`
-   `F-Log2C`
-   `V-Log`
-   `N-Log`
-   `Canon Log 2`
-   `Canon Log 3`
-   `S-Log3`
-   `S-Log3.Cine`
-   `LogC3`
-   `LogC4`
-   `Log3G10`