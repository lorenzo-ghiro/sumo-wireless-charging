import argparse
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

plt.rcParams.update({"text.usetex": True, "font.family": "sans-serif",
                     "font.sans-serif": ["Arial"], "axes.grid": True})

def parse_args():
    p = argparse.ArgumentParser(description="Plot satisfaction distribution comparing opt vs benchmark")
    p.add_argument("--opt", required=True, help="Path to opt satisfaction_moments parquet file")
    p.add_argument("--benchmark", required=True, help="Path to benchmark satisfaction_moments parquet file")
    p.add_argument("--kind", default="ecdf", choices=["ecdf", "pdf"], help="Type of plot: 'ecdf' or 'pdf' (default: ecdf)")
    p.add_argument("--output", default=None, help="Output filename (default: auto-generated)")
    return p.parse_args()


def plot_satis_distribution(merged_df, kind='ecdf'):
    """
    Create distribution plot of soc_fulfillment at arrival, comparing opt vs benchmark.
    
    Parameters:
    - merged_df: DataFrame with columns [soc_fulfillment, exptype, ...]
    - kind: 'ecdf' for empirical CDF or 'pdf' for probability density function
    """
    # Map labels to uppercase
    merged_df = merged_df.copy()
    merged_df['exptype'] = merged_df['exptype'].map({'opt': 'OPT', 'benchmark': 'BENCH'})
    
    print(f"Plotting {len(merged_df)} arrival moments")
    print(f"Opt arrivals: {len(merged_df[merged_df['exptype']=='OPT'])}")
    print(f"Benchmark arrivals: {len(merged_df[merged_df['exptype']=='BENCH'])}")
    print(f"soc_fulfillment range: [{merged_df['soc_fulfillment'].min():.3f}, {merged_df['soc_fulfillment'].max():.3f}]")
    
    # Calculate means for each distribution
    opt_mean = merged_df[merged_df['exptype']=='OPT']['soc_fulfillment'].mean()
    benchmark_mean = merged_df[merged_df['exptype']=='BENCH']['soc_fulfillment'].mean()
    print(f"Opt mean: {opt_mean:.3f}")
    print(f"Benchmark mean: {benchmark_mean:.3f}")
    
    # Create single figure
    fig, ax = plt.subplots(1, 1, figsize=(4.2, 2.3))
    
    # Define explicit order for hue and get color palette
    hue_order = ['BENCH', 'OPT']
    palette = sns.color_palette()[:len(hue_order)]
    
    # Create the plot based on kind
    if kind == 'ecdf':
        # ECDF plot
        sns.ecdfplot(data=merged_df, x="soc_fulfillment", hue="exptype", hue_order=hue_order,
                     ax=ax, legend=True, linewidth=2, palette=palette)
        ax.set_ylabel("CDF")
        ax.set_xlim(0, 1)
    else:  # kind == 'pdf'
        # Smooth probability density curves
        sns.kdeplot(data=merged_df, x="soc_fulfillment", hue="exptype", hue_order=hue_order,
                    ax=ax, legend=False, linewidth=2, palette=palette, fill=True, alpha=0.3,
                    common_norm=False, cut=0)
        ax.set_ylabel("PDF")
        ax.set_xlim(0, 0.25)
        
        # Create custom legend with lines instead of boxes
        custom_handles = [Line2D([0], [0], color=palette[i], linewidth=2) for i in range(len(hue_order))]
        ax.legend(custom_handles, hue_order, frameon=True, fontsize=9)
    
    ax.set_xlabel(r"$\phi_v$")
    
    ax.grid(True, alpha=0.3)
    
    # Adjust legend (for ecdf, already created by seaborn)
    if kind == 'ecdf':
        legend = ax.get_legend()
        if legend:
            legend.set_title(None)
            legend.set_frame_on(True)
            for text in legend.get_texts():
                text.set_fontsize(9)
    
    plt.tight_layout()
    
    return fig


def main():
    a = parse_args()
    
    print(f"Loading opt data from {a.opt}")
    opt_df = pd.read_parquet(a.opt)
    opt_df['exptype'] = 'opt'
    
    print(f"Loading benchmark data from {a.benchmark}")
    benchmark_df = pd.read_parquet(a.benchmark)
    benchmark_df['exptype'] = 'benchmark'
    
    # Merge both dataframes
    merged_df = pd.concat([opt_df, benchmark_df], ignore_index=True)
    
    print(f"Merged {len(merged_df)} total rows")
    print(f"Unique moments: {merged_df['moment'].unique()}")
    
    # Filter for arrival moments only
    arrival_df = merged_df[merged_df['moment'] == 'arrival'].copy()
    
    print(f"Filtered to {len(arrival_df)} arrival moments")
    
    # Plot distribution
    fig = plot_satis_distribution(arrival_df, kind=a.kind)
    
    if a.output is None:
        output_filename = f"satis_{a.kind}_opt_vs_benchmark.pdf"
    else:
        output_filename = a.output
    
    # Save plot
    fig.savefig(output_filename, format="pdf", bbox_inches="tight")
    print(f"Saved distribution plot to {output_filename}")


if __name__ == "__main__":
    main()
