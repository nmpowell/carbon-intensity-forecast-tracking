import colorsys
import os
from datetime import datetime

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm
from matplotlib.colors import ListedColormap

CI_BANDS_FILEPATH = os.path.join(
    os.path.abspath(os.path.dirname(__file__)),
    "..",
    "data",
    "artifacts",
    "ci_index_numerical_bands.csv",
)

# Generated from: https://www.joshwcomeau.com/gradient-generator/?angle=0&easingCurve=0.25%7C0.75%7C0.75%7C0.25&precision=20&colorMode=hcl&colors=00ea00%7Cffea00%7Cff0000
CSS_HSL = [
    (120, 100, 46),
    (101, 100, 46),
    (94, 100, 46),
    (88, 100, 46),
    (82, 100, 46),
    (78, 100, 46),
    (73, 100, 46),
    (69, 100, 46),
    (65, 100, 46),
    (62, 100, 46),
    (58, 100, 47),
    (55, 100, 50),
    (52, 100, 50),
    (48, 100, 50),
    (44, 100, 50),
    (41, 100, 50),
    (37, 100, 50),
    (33, 100, 50),
    (29, 100, 50),
    (24, 100, 50),
    (19, 100, 50),
    (13, 100, 50),
    (0, 100, 50),
]


def hsl_to_rgb(h, s, l):
    return colorsys.hls_to_rgb(h / 360, l / 100, s / 100)


def _preview_colourmap(cmap):
    gradient = np.linspace(0, 1, 256)
    gradient = np.vstack((gradient, gradient))

    fig, ax = plt.subplots()
    ax.imshow(gradient, aspect="auto", cmap=cmap)
    plt.xticks([])
    plt.yticks([])
    plt.show()


def get_boundaries(year: int = 2023) -> (list, list):
    """Returns the numerical boundaries for the CI index for a given year.

    Args:
        year (int, optional): The year to use from the bands table. Defaults to 2023.

    Returns:
        tuple: The numerical boundaries for the CI index for a given year.
    """
    # Load the CSV containing the CI index numerical boundaries
    df = pd.read_csv(CI_BANDS_FILEPATH, index_col=0, header=[0, 1])
    values_from = df.loc[year, pd.IndexSlice[:, ["from"]]].to_list()
    band_names = df.columns.get_level_values(0).unique().to_list()
    return band_names, values_from


def generate_colourmap(boundary_values: list):
    """Generates a colourmap to be used as a background for plots."""

    colours = [hsl_to_rgb(*hsl) for hsl in CSS_HSL]
    colour_positions = np.linspace(0, 1, len(colours))
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "green_yellow_red_cmap", list(zip(colour_positions, colours))
    )

    # Select colours from the original colormap
    selected_colors = [cmap(i) for i in np.linspace(0, 1, 5)]

    # Create a qualitative colormap with 5 distinct colors
    qualitative_cmap = mcolors.ListedColormap(selected_colors)

    # Define the new boundaries
    boundaries = [*boundary_values, max(boundary_values) + 1]

    # Create a new BoundaryNorm with the new boundaries
    norm = BoundaryNorm(boundaries, qualitative_cmap.N)

    # Create a ListedColormap with the desired colors
    listed_cmap = ListedColormap(qualitative_cmap.colors)

    return listed_cmap, norm


def add_colourmap(
    ax,
    year: int = None,
) -> None:
    """_summary_

    Args:
        ax (_type_): _description_
        year (int, optional): The year to use from the bands table. Defaults to the current year.
    """

    year = year if year else datetime.now().year

    # Load the CSV containing the CI index numerical boundaries
    y_labels, y_tick_values = get_boundaries(year)

    listed_cmap, norm = generate_colourmap(y_tick_values)

    ax2 = ax.twinx()
    ax2.set(ylim=ax.get_ylim(), yticks=y_tick_values, yticklabels=y_labels)
    ax2.set_yticklabels(y_labels, verticalalignment="bottom")

    ylims = ax.get_ylim()
    xlims = ax.get_xlim()

    # do this last to align the secondary axis labels with the primary
    ax2.set_ylim(ylims)

    # Generate an array of values covering the whole y axis
    y_range = np.arange(ylims[0], ylims[1], 0.01)
    # has to be reversed in this case
    yarr = np.vstack(y_range[::-1])

    # Show the colourmap as the background to the plot
    ax.imshow(
        yarr,
        extent=(xlims[0], xlims[1], ylims[0], ylims[1]),
        cmap=listed_cmap,
        norm=norm,
        alpha=0.5,
        aspect="auto",
        interpolation="nearest",
    )
