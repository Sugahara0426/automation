# ==================================================
# fit_vna_min.py
#
# VNA resonance analysis
#
# Resonance frequency is determined by
# the minimum value of Narrow S11.
#
# ==================================================

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ==================================================
# Target frequency [GHz]
# ==================================================

TARGET_FREQ = {

    "110": 1.906,
    "210": 2.556,

}

# ==================================================
# Measurement modes
# ==================================================

BANDS = {

    "110": [
        "110_Wide",
        "110_Narrow"
    ],

    "210": [
        "210_Wide",
        "210_Narrow"
    ]

}

PARAMS = [

    ("S11", "S11_Amp_Mean", "|S11|"),
    ("S21", "S21_Amp_Mean", "|S21|")

]

# ==================================================
# Find resonance frequency
# ==================================================

def find_resonance(freq, amp):

    idx = np.argmin(amp)

    f0 = freq.iloc[idx]

    amp_min = amp.iloc[idx]

    return idx, f0, amp_min

# ==================================================
# Main
# ==================================================

def analyze(csv_path):

    if not os.path.exists(csv_path):

        raise FileNotFoundError(csv_path)

    csv_name = os.path.splitext(
        os.path.basename(csv_path)
    )[0]

    save_dir = f"figures/{csv_name}"

    os.makedirs(
        save_dir,
        exist_ok=True
    )

    df_all = pd.read_csv(csv_path)

    results = {}

    # ==================================================
    # Plot
    # ==================================================

    for band, modes in BANDS.items():

        fig, axes = plt.subplots(
            2,
            2,
            figsize=(12, 8)
        )

        fig.suptitle(
            f"{band} band",
            fontsize=15
        )

        for row, mode in enumerate(modes):

            df = df_all[
                df_all["Measurement_Mode"] == mode
            ]

            if len(df) == 0:
                print(f"Warning : {mode} not found.")
                continue

            freq = df["Frequency [Hz]"] / 1e9

            for col, (param_name, amp_col, ylabel) in enumerate(PARAMS):

                ax = axes[row, col]

                amp = df[amp_col]

                # --------------------------
                # Raw data
                # --------------------------

                ax.plot(
                    freq,
                    amp,
                    lw=1.5,
                    label="Data"
                )

                # --------------------------
                # Resonance search
                # --------------------------

                if (
                    param_name == "S11"
                    and
                    "Narrow" in mode
                ):

                    idx, f0, amp_min = find_resonance(
                        freq,
                        amp
                    )

                    target = TARGET_FREQ[band]

                    delta = (
                        f0 - target
                    ) * 1000

                    results[mode] = {

                        "Target": target,

                        "f0": f0,

                        "Delta": delta

                    }

                    # 最小点を赤丸で表示

                    ax.plot(
                        f0,
                        amp_min,
                        "ro",
                        markersize=8,
                        label="Minimum"
                    )

                    # 縦線

                    ax.axvline(
                        f0,
                        color="red",
                        linestyle="--",
                        alpha=0.7
                    )

                    text = (

                        f"$f_0$ = {f0:.6f} GHz\n"

                        f"$\\Delta f$ = {delta:+.3f} MHz"

                    )

                    ax.text(

                        0.03,

                        0.03,

                        text,

                        transform=ax.transAxes,

                        fontsize=10,

                        bbox=dict(
                            facecolor="white",
                            alpha=0.85
                        )

                    )

                    ax.legend()

                ax.set_title(
                    f"{mode} {param_name}"
                )

                ax.set_xlabel(
                    "Frequency [GHz]"
                )

                ax.set_ylabel(
                    ylabel
                )

                ax.grid(True)

        fig.tight_layout()

        fig.savefig(
            f"{save_dir}/{band}_band.png",
            dpi=300,
            bbox_inches="tight"
        )

        plt.close(fig)

    # ==================================================
    # Console output
    # ==================================================

    print("\n" + "=" * 60)
    print("Minimum Search Results")
    print("=" * 60)

    for mode, result in results.items():

        print("\n" + mode)

        print(
            f"Target Frequency : "
            f"{result['Target']:.6f} GHz"
        )

        print(
            f"Resonance f0     : "
            f"{result['f0']:.6f} GHz"
        )

        print(
            f"Difference       : "
            f"{result['Delta']:+.3f} MHz"
        )

    print("\nSaved figures:")
    print(save_dir)

    return results


# ==================================================
# Standalone execution
# ==================================================

if __name__ == "__main__":

    csv_path = input(
        "CSV file path : "
    )

    analyze(csv_path)
