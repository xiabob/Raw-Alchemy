import click
from . import core

@click.command()
@click.argument("input_raw", type=click.Path(exists=True))
@click.argument("output_tiff", type=click.Path())
@click.option(
    "--log-space",
    default="F-Log2",
    type=click.Choice(list(core.LOG_TO_WORKING_SPACE.keys()), case_sensitive=False),
    help="The log space to convert to.",
)
@click.option(
    "--lut",
    "lut_path",
    type=click.Path(exists=True),
    help="Path to a .cube LUT file to apply.",
)
@click.option(
    "--lut-space",
    type=click.Choice(["Rec.709", "Rec.2020"], case_sensitive=False),
    help="Output color space of the LUT (e.g., Rec.709, Rec.2020). Required if --lut is used.",
)
@click.option(
    "--matrix-method",
    default="metadata",
    type=click.Choice(["metadata", "adobe"], case_sensitive=False),
    help="The matrix to use for RAW to ACES conversion.",
)
@click.option(
    "--exposure",
    type=float,
    default=None,
    help="Manual exposure adjustment in stops (e.g., -0.5, 1.0). Overrides all auto exposure.",
)
def main(input_raw, output_tiff, log_space, lut_path, lut_space, matrix_method, exposure):
    """
    Converts a RAW image to a TIFF file through an ACES-based pipeline.
    """
    if lut_path and not lut_space:
        raise click.UsageError("`--lut-space` is required when using `--lut`.")

    click.echo(f"Processing {input_raw}...")

    core.process_image(
        raw_path=input_raw,
        output_path=output_tiff,
        log_space=log_space,
        lut_path=lut_path,
        lut_space=lut_space,
        matrix_method=matrix_method,
        exposure=exposure,
    )

    click.echo(f"Successfully saved to {output_tiff}")


if __name__ == "__main__":
    main()