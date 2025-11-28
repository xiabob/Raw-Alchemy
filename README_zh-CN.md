# Raw Alchemy

[English](README.md)

---

一个基于 Python 的命令行工具，用于实现高级 RAW 图像处理流程。它旨在将 RAW 文件转换到 ACES (学院色彩编码系统) 框架下的场景线性空间，应用相机特定的 Log 曲线，并集成创意 LUT，以实现一个完整且色彩管理精确的工作流。

### 核心理念

许多摄影师和摄像师都依赖创意 LUT (色彩查找表) 来实现特定的视觉风格。然而，一个普遍的痛点是：**将在视频工作流中表现完美的 LUT 应用于 RAW 格式的照片时，色彩往往会出错。**

这个问题源于色彩空间的不匹配。大多数创意 LUT 被设计用于特定的 Log 色彩空间 (例如索尼的 S-Log3/S-Gamut3.Cine 或富士的 F-Log2/F-Gamut)。当您在 Photoshop 或 Lightroom 中打开一张 RAW 照片并直接应用这些 LUT 时，软件默认的 RAW 解码色彩空间与 LUT 期望的输入空间不符，导致色彩和影调的严重偏差。

**Raw Alchemy** 正是为解决这一问题而生。它通过构建一个严谨、自动化的色彩管线，确保任何 LUT 都能被精确地应用于任何 RAW 文件：

1.  **标准化解码 -> ACES**: 项目首先将任何来源的 RAW 文件解码到一个标准化的、超广色域的中间空间——ACES AP0 (线性)。这消除了不同品牌相机自带的色彩科学差异，为所有操作提供了一个统一的、与设备无关的起点。
2.  **精确准备 Log 信号**: 接着，它将 ACES 空间的图像数据，精确地转换为目标 LUT 所期望的 Log 格式，例如 `F-Log2` 曲线和 `F-Gamut` 色域。这一步是确保色彩一致性的关键，它完美模拟了相机内部生成 Log 视频信号的过程。
3.  **正确应用 LUT**: 在这个被精确“伪装”好的 Log 图像上应用您的创意 LUT，其色彩和影调表现将与在专业视频软件 (如达芬奇) 中完全一致。
4.  **色彩管理的输出**: 最后，将经过 LUT 处理的图像从广色域安全地转换到标准的 Adobe RGB (1998) 空间，生成 16 位 TIFF 文件，确保最终结果在不同设备上观看和打印时，色彩依然准确。

通过这个流程，`Raw Alchemy` 打破了 RAW 摄影与专业视频调色之间的壁垒，让摄影师也能享受到电影级别的色彩管理精度。

### 处理流程

本工具遵循以下精确的色彩转换步骤：

`RAW (相机原生)` -> `ACES AP0 (线性)` -> `相机色域 (线性)` -> `相机 Log (例如 F-Log2)` -> `(可选) 创意 LUT` -> `Adobe RGB (1998) TIFF`

### 特性

-   **RAW 转 ACES**: 将 RAW 文件直接解码到 ACES AP0 (线性) 工作色彩空间。
-   **Log 转换**: 支持多种相机特定的 Log 格式（F-Log2, S-Log3, LogC4 等）。
-   **LUT 应用**: 应用 `.cube` LUT 文件进行创意调色。
-   **曝光控制**: 提供三级曝光逻辑：手动曝光覆盖、基于元数据的 `BaselineExposure`、或自动中性灰曝光。
-   **高质量输出**: 将最终图像以 Adobe RGB (1998) 色彩空间保存为 16 位 TIFF 文件。
-   **技术栈**: 使用 `rawpy` 进行 RAW 解码，并利用 `colour-science` 进行高精度色彩转换。

### 安装

本项目有几个关键依赖项，它们有特定的安装要求，请严格按照以下步骤操作。

**第一步：安装 `rawpy` 分支**

`rawpy` 依赖于操作系统级别的库，其安装过程因系统而异。请访问项目所需的 `rawpy` 分支仓库，并严格遵循其 `README` 文件中的详细安装指南：

➡️ **[https://github.com/shenmintao/rawpy.git](https://github.com/shenmintao/rawpy.git)**

在继续下一步之前，请确保您可以在 Python 环境中成功执行 `import rawpy`。

**第二步：安装 `colour-science`**

从 GitHub 安装所需的开发分支：
```bash
pip install git+https://github.com/colour-science/colour.git@develop
```

**第三步：安装 Raw Alchemy**

在上述依赖项全部成功安装后，即可安装本项目。
```bash
# 克隆本仓库
git clone https://github.com/shenmintao/raw-alchemy.git
cd raw-alchemy

# 安装工具
pip install .
```

### 使用方法

通过 `raw-alchemy` 命令来使用该工具。

#### 基本语法

```bash
raw-alchemy [OPTIONS] <INPUT_RAW_PATH> <OUTPUT_TIFF_PATH>
```

#### 示例 1: 基本 Log 转换

此示例将一个 RAW 文件转换为 ACES，然后应用 F-Log2 曲线，并将结果以 Adobe RGB 色彩空间保存为 TIFF 文件。

```bash
raw-alchemy "path/to/your/image.CR3" "path/to/output/image.tiff" --log-space "F-Log2"
```

#### 示例 2: 使用创意 LUT 进行转换

此示例转换 RAW 文件，应用 S-Log3 曲线，然后应用一个创意 LUT (`my_look.cube`)，并保存最终结果。

**重要提示**: 使用 LUT 时，您必须通过 `--lut-space` 指定该 LUT 的输出色彩空间。这通常是 `Rec.709` 或 `Rec.2020`。

```bash
raw-alchemy "input.ARW" "output.tiff" --log-space "S-Log3" --lut "looks/my_look.cube" --lut-space "Rec.709"
```

#### 示例 3: 使用 Adobe 矩阵进行转换

此示例强制使用 `rawpy` 内置的 Adobe 系数矩阵进行初始 RAW 解码，而不是依赖文件元数据。

```bash
raw-alchemy "input.NEF" "output_adobe.tiff" --matrix-method "adobe"
```

#### 示例 4: 手动曝光调整

此示例手动应用 +1.5 档的曝光补偿，它将覆盖任何元数据或自动曝光逻辑。

```bash
raw-alchemy "input.CR3" "output_bright.tiff" --exposure 1.5
```

### 命令行选项

-   `<INPUT_RAW_PATH>`: (必需) 输入的 RAW 文件路径 (例如 .CR3, .ARW, .NEF)。
-   `<OUTPUT_TIFF_PATH>`: (必需) 输出的 16 位 TIFF 文件的保存路径。

-   `--log-space TEXT`: (可选, 默认: `F-Log2`) 目标 Log 色彩空间。
-   `--matrix-method TEXT`: (可选, 默认: `metadata`) 用于 RAW 到 ACES 转换的矩阵。
    -   `metadata`: 使用相机文件元数据中的矩阵。通常是最准确的选项。
    -   `adobe`: 强制使用 LibRaw 内置的 Adobe 系数矩阵。
-   `--exposure FLOAT`: (可选) 手动曝光调整，单位为档 (stops)，例如 -0.5, 1.0。此选项会覆盖所有自动曝光逻辑。
-   `--lut TEXT`: (可选) 在 Log 转换后应用的 `.cube` LUT 文件路径。
-   `--lut-space TEXT`: (如果使用了 `--lut` 则必需) LUT 的输出色彩空间。必须是 `Rec.709` 或 `Rec.2020` 之一。

### 支持的 Log 空间

`--log-space` 选项支持以下值:
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