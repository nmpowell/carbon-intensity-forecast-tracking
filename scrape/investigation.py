import os

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import curve_fit

INDEX_BANDS_PATH = "../data/artifacts/ci_index_numerical_bands.csv"
INDEX_BANDS_ERROR_SCALES_PATH = (
    "../data/artifacts/ci_index_numerical_band_error_scales.csv"
)


# This .csv is created in the Investigations Notebook.
def problem_magnitudes(year: int = 2023, column_name: str = "difference"):
    path = os.path.join(os.path.dirname(__file__), INDEX_BANDS_ERROR_SCALES_PATH)
    df = pd.read_csv(path, index_col=0, header=[0, 1])
    return df.loc[year, pd.IndexSlice[:, [column_name]]].values.tolist()


def cleanup(df: pd.DataFrame, column_name: str, max_cutoff: int = 200) -> np.array:
    # Ignore extreme outliers

    c = df.loc[df[column_name].abs() > max_cutoff, column_name].count()
    n = df[column_name].isna().sum()

    df_corr = df.copy()
    df_corr.loc[df_corr[column_name] > max_cutoff, column_name] = np.nan
    df_corr.loc[df_corr[column_name] < -max_cutoff, column_name] = np.nan

    # Get non-NaNs
    data = df_corr[np.isfinite(df_corr[column_name])][column_name].values
    print(f"{c} excluded outliers, {n} nans, leaving {len(data)} data points")
    return data


def normal_distribution(x, mu, sigma):
    return stats.norm.pdf(x, loc=mu, scale=sigma)


def t_distribution(x, mu, sigma, nu):
    return stats.t.pdf(x, df=nu, loc=mu, scale=sigma)


def laplace_distribution(x, mu, b):
    return stats.laplace.pdf(x, loc=mu, scale=b)


def histogram(data, n_bins, density: bool = True):
    # Calculate histogram data
    hist, bin_edges = np.histogram(data, bins=n_bins, density=True)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    # Calculate the bin width
    bin_width = bin_edges[1] - bin_edges[0]
    return hist, bin_edges, bin_centers, bin_width


def distribution_parameters(
    data, n_bins, density: bool = True, lookup_values: list = []
):
    # Mean, standard deviation, degrees of freedom
    mu = np.mean(data)
    sigma = np.std(data)
    nu = len(data) - 1

    # Get histogram parameters
    hist, bin_edges, bin_centers, bin_width = histogram(data, n_bins, density)

    # Generate an x-axis
    x_bin_centres = np.linspace(bin_edges[0], bin_edges[-1], 1000)

    distribution_data = {
        "Normal": {
            "distn_fn": normal_distribution,
            "distn_params": ["mean", "standard deviation"],
            "cdf_fn": stats.norm.cdf,
            "cdf_params": ["loc", "scale"],
            "curve_params": [mu, sigma],
            "ppf_fn": stats.norm.ppf,
        },
        "Student's t": {
            "distn_fn": t_distribution,
            "distn_params": ["mean", "standard deviation", "degrees of freedom"],
            "cdf_fn": stats.t.cdf,
            "cdf_params": ["loc", "scale", "df"],
            "curve_params": [mu, sigma, nu],
            "ppf_fn": stats.t.ppf,
        },
        "Laplace": {
            "distn_fn": laplace_distribution,
            "distn_params": ["mean", "scale"],
            "cdf_fn": stats.laplace.cdf,
            "cdf_params": ["loc", "scale"],
            "curve_params": [mu, sigma],
            "ppf_fn": stats.laplace.ppf,
        },
    }

    distn_results, cdf_results, ppf_results, extreme_data = {}, {}, {}, {}
    extreme_data["values"] = lookup_values

    for name, data in distribution_data.items():
        # fit the distribution
        fn = data.get("distn_fn")
        popt, _ = curve_fit(fn, bin_centers, hist, p0=data.get("curve_params"))
        print(f"{name} distribution parameters:")
        print(dict(zip(data.get("distn_params"), popt)))

        # For plotting the fitted distributions scaled by the number of data points and bin width
        distn_results[name] = (
            fn(x_bin_centres, *popt)
            if density
            else fn(x_bin_centres, *popt) * bin_width * len(data)
        )
        params = dict(zip(data.get("cdf_params"), popt))
        cdf_results[name] = data.get("cdf_fn")(x_bin_centres, **params)
        ppf_results[name] = data.get("ppf_fn")([0.025, 0.975], **params)

        # Get the total probability of specific extreme values (positive and negative)
        total_extreme_probs = []
        for val in lookup_values:
            val = np.abs(val)
            total_extreme_probs.append(
                sum(
                    [
                        1 - data.get("cdf_fn")(val, **params),
                        data.get("cdf_fn")(-1.0 * val, **params),
                    ]
                )
            )
        extreme_data[name + " probability"] = total_extreme_probs

    return (
        x_bin_centres,
        distn_results,
        cdf_results,
        pd.DataFrame(extreme_data),
    )


def prob_extreme_t(extreme_value, popt_t):
    """Using extreme values +/-"""

    extreme_value = np.abs(extreme_value)
    results = []

    # Student's t-distribution
    t_cdf = stats.t.cdf(extreme_value, df=popt_t[2], loc=popt_t[0], scale=popt_t[1])
    results.append(1 - t_cdf)

    t_cdf = stats.t.cdf(
        extreme_value * -1.0, df=popt_t[2], loc=popt_t[0], scale=popt_t[1]
    )
    results.append(t_cdf)
    return results


def prob_extreme_laplace(extreme_value, popt_laplace):
    """Using extreme values +/-"""

    extreme_value = np.abs(extreme_value)
    results = []

    # Laplace distribution
    laplace_cdf = stats.laplace.cdf(
        extreme_value, loc=popt_laplace[0], scale=popt_laplace[1]
    )
    results.append(1 - laplace_cdf)

    laplace_cdf = stats.laplace.cdf(
        extreme_value * -1.0, loc=popt_laplace[0], scale=popt_laplace[1]
    )
    results.append(laplace_cdf)
    return results
