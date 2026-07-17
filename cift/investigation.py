import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import curve_fit

# This .csv is created in the Investigations Notebook.


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
    data, n_bins, density: bool = True, lookup_values: list | None = None
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
        "Student's t": {
            "distn_fn": t_distribution,
            "distn_params": ["mean", "standard deviation", "degrees of freedom"],
            "cdf_fn": stats.t.cdf,
            "cdf_params": ["loc", "scale", "df"],
            "curve_params": [mu, sigma, nu],
            "ppf_fn": stats.t.ppf,
        },
        "Normal": {
            "distn_fn": normal_distribution,
            "distn_params": ["mean", "standard deviation"],
            "cdf_fn": stats.norm.cdf,
            "cdf_params": ["loc", "scale"],
            "curve_params": [mu, sigma],
            "ppf_fn": stats.norm.ppf,
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
    lookup_values = lookup_values or []
    extreme_data["error value"] = lookup_values

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
        pd.DataFrame(extreme_data).set_index("error value"),
    )
