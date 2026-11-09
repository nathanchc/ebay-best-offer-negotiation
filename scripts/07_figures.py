"""Figures for the README / report, from reports/tables/*.csv.  Usage (repo root): python -I scripts/07_figures.py"""
import pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
import os
SMOKE = os.environ.get("SMOKE") == "1"
T = ROOT / "reports" / ("tables_smoke" if SMOKE else "tables")
F = ROOT / ("figures_smoke" if SMOKE else "figures")
F.mkdir(exist_ok=True)

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2 = "#2a78d6", "#eb6834"           # categorical slots 1-2 (validated reference palette)
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "sans-serif", "font.size": 10, "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": GRID, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.titleweight": "bold", "axes.axisbelow": True, "axes.titlesize": 12, "axes.titlelocation": "left",
})


def pct(x): return f"{x * 100:.1f}"


def finish(fig, name, source=True):
    if source:
        fig.text(0.01, -0.04, "Data: eBay Best Offer, 2012-13 (Backus, Blake, Larsen & Tadelis, QJE 2020)",
                 fontsize=8, color=INK2)
    fig.savefig(F / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("wrote", F / name)


# 1 -- the message gap under stricter comparisons (dot + 95% interval), all categories vs clothing
b = pd.read_csv(T / "p2b_matched_gap.csv").set_index("segment")
c = pd.read_csv(T / "p2c_same_listing.csv").set_index("segment")
rows = []
for seg, lab in [("All categories", "All categories"), ("Clothing", "Clothing, shoes & acc.")]:
    rows += [(lab, "Raw difference", b.loc[seg, "raw_gap"], None),
             (lab, "Same category, price, discount,\nexperience and condition", b.loc[seg, "matched_gap"], b.loc[seg, "matched_se"]),
             (lab, "Same listing (buyers bidding\non the same item)", c.loc[seg, "coef"], c.loc[seg, "se"])]
d = pd.DataFrame(rows, columns=["seg", "cmp", "est", "se"])
fig, ax = plt.subplots(figsize=(8, 4.2))
order = d["cmp"].unique()[::-1]
for i, (seg, col, off) in enumerate([("All categories", S1, 0.14), ("Clothing, shoes & acc.", S2, -0.14)]):
    dd = d[d.seg == seg].set_index("cmp").loc[order]
    y = [k + off for k in range(len(order))]
    err = [1.96 * s * 100 if pd.notna(s) else 0 for s in dd["se"]]
    ax.errorbar(dd["est"] * 100, y, xerr=err, fmt="o", color=col, ms=8, lw=2, capsize=0,
                markeredgecolor=SURFACE, markeredgewidth=2, label=seg)
    for yy, v in zip(y, dd["est"]):
        ax.annotate(f"{v * 100:+.1f}", (v * 100, yy), xytext=(0, 7), textcoords="offset points",
                    ha="center", fontsize=8.5, color=INK)
ax.axvline(0, color=INK2, lw=1)
ax.set_yticks(range(len(order)), order)
ax.set_xlabel("Difference in deal rate, offers with vs without a message (percentage points)")
ax.grid(axis="y", visible=False)
ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9)
ax.set_title("The stricter the comparison, the smaller the message effect", pad=26)
finish(fig, "fig1_message_gap.png")

# 2 -- what happens to opening offers
f = pd.read_csv(T / "p3_opening_funnel.csv").sort_values("share")
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.barh(f["opening_offer_outcome"], f["share"] * 100, color=S1, height=0.6, edgecolor=SURFACE, linewidth=2)
for y, (s, r) in enumerate(zip(f["share"], f["eventual_deal_rate"])):
    ax.text(s * 100 + 0.6, y, f"{pct(s)}%   · {pct(r)}% end in a deal", va="center", fontsize=8.5, color=INK2)
ax.set_xlabel("Share of opening offers (%)")
ax.grid(axis="y", visible=False)
ax.set_xlim(0, f["share"].max() * 100 * 1.65)
ax.set_title("What happens to a buyer's opening offer")
finish(fig, "fig2_opening_funnel.png")

# 3 -- seller counter speed vs eventual deal
s = pd.read_csv(T / "p3_reply_speed.csv")
s = s[s.open_status == 7].copy()
s["label"] = s["seller_reply_time"].str[2:]
fig, ax = plt.subplots(figsize=(6.5, 3.6))
ax.bar(s["label"], s["eventual_deal_rate"] * 100, color=S1, width=0.6, edgecolor=SURFACE, linewidth=2)
for x, v in enumerate(s["eventual_deal_rate"]):
    ax.text(x, v * 100 + 0.6, f"{pct(v)}%", ha="center", fontsize=9, color=INK)
ax.set_ylabel("Negotiations ending in a deal (%)")
ax.set_xlabel("Time until the seller's counteroffer")
ax.grid(axis="x", visible=False)
ax.set_title("Negotiations with slower counteroffers end in fewer deals")
finish(fig, "fig3_counter_speed.png")

# 4 -- near-miss auto-declines
n = pd.read_csv(T / "p3_near_miss_auto_declines.csv")
lab = {"within 10% of threshold": "Within 10%", "10-25% below": "10-25% below", "more than 25% below": "Over 25% below"}
n["label"] = n["distance_to_auto_decline_threshold"].map(lab)
n = n.set_index("label").loc[list(lab.values())]
fig, ax = plt.subplots(figsize=(7, 3.8))
x = range(len(n))
w = 0.36
ax.bar([i - w / 2 - 0.01 for i in x], (1 - n["share_reopened"]) * 100, w, color=S2, label="Buyer gave up (never re-offered)")
ax.bar([i + w / 2 + 0.01 for i in x], n["eventual_deal_rate"] * 100, w, color=S1, label="Ended in a deal anyway")
for i, (g, dl) in enumerate(zip(1 - n["share_reopened"], n["eventual_deal_rate"])):
    ax.text(i - w / 2 - 0.01, g * 100 + 0.8, f"{pct(g)}%", ha="center", fontsize=8.5)
    ax.text(i + w / 2 + 0.01, dl * 100 + 0.8, f"{pct(dl)}%", ha="center", fontsize=8.5)
ax.set_xticks(list(x), n.index)
ax.set_xlabel("Opening offer's distance below the seller's hidden auto-decline price")
ax.set_ylabel("Share of auto-declined offers (%)")
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, fontsize=9, loc="upper left")
ax.set_title("Near-miss offers are auto-declined, and many buyers walk away")
finish(fig, "fig4_near_miss.png")
