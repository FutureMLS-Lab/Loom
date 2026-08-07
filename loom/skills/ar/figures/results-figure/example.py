"""A worked results figure, from AAAI-27 paper 45654. Run it to see the output.

The claim is that no existing parameter can stand in for the recurrence time T.
Top: T grows exponentially in |S|, so no polynomial in |S| bounds it. Bottom: T
grows while the average-reward parameters B and H stay identically zero, so a
bound written in B+H is vacuous exactly where T is not.

Two conventions worth copying from it. The polynomial references in the top
panel are *anchored at the first data point*, so the eye compares growth rates
rather than constants -- on a log axis an exponential is straight and every
polynomial bends away. And the bottom panel shades between the two series, so
the gap the paragraph is about is the thing the reader sees.

The numbers are the exact epsilon-recurrence times of the paper's Definition 1,
computed by forward propagation rather than sampling, and cached here.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "scripts"))
import plot_style as ps                                       # noqa: E402
from plot_style import BLUE, COL, GREY, ORANGE, VERM, plt      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, "example_data.json")))
lock, cyc = data["lock"], data["cycle"]

fig, ax = plt.subplots(2, 1, figsize=(COL, 3.5))
fig.subplots_adjust(left=0.165, right=0.985, top=0.975, bottom=0.115,
                    hspace=0.55)

# ------------------------------------------------- top: T is exponential in |S|
ms = [r["m"] for r in lock]
Ts = [r["T"] for r in lock]
m0, T0 = ms[0], Ts[0]

for expo, label, style in [(1, r"$|S|$", (0, (1, 2))),
                           (2, r"$|S|^2$", (0, (4, 2))),
                           (3, r"$|S|^3$", (0, (6, 2, 1, 2)))]:
    ax[0].plot(ms, [T0 * (m / m0) ** expo for m in ms], ls=style, color=GREY,
               lw=0.9, label=label)
ax[0].plot(ms, [T0 * 2 ** (m - m0) for m in ms], "-", color=ORANGE, lw=1.0,
           alpha=0.9, label=r"$2^{|S|}$")
ax[0].plot(ms, Ts, "o-", color=BLUE, label=r"measured $T$")

ps.logticks(ax[0], [10, 100, 1000, 10000])
ax[0].set_xlabel(r"number of states $|S|$   (combination lock)")
ax[0].set_ylabel(r"$\epsilon$-recurrence time $T$")
ax[0].set_xticks(list(ms))
ax[0].set_ylim(4, 4e4)
ratio = Ts[-1] / Ts[-2]
ax[0].annotate(fr"$T(|S|)/T(|S|-1)\to{ratio:.3f}$", xy=(ms[-1], Ts[-1]),
               xytext=(-2, 9), textcoords="offset points", ha="right",
               fontsize=6.6, color=BLUE)
ax[0].legend(loc="upper left", ncol=2, **ps.LEGEND)

# ------------------------------- bottom: B and H are blind to what T measures
Ls = [r["L"] for r in cyc]
cT = [r["T"] for r in cyc]
cBH = [r["BH"] for r in cyc]

ax[1].plot(Ls, cT, "o-", color=BLUE, label=r"$T$ (this paper)")
ax[1].plot(Ls, cBH, "s-", color=VERM,
           label=r"$\mathsf{B}+\mathsf{H}$ (average reward)")
ax[1].fill_between(Ls, cBH, cT, color=BLUE, alpha=0.10, lw=0)

ax[1].set_xlabel(r"number of states $|S|$   (deterministic cycle)")
ax[1].set_ylabel("parameter value")
ax[1].set_xticks(list(Ls))
ax[1].set_ylim(-1.5, 27)
ax[1].annotate(r"$\Omega\!\left(|S||A|(\mathsf{B}+\mathsf{H})/\epsilon^2\right)$"
               "\nis vacuous here", xy=(7, 1.0), ha="center", va="bottom",
               fontsize=6.6, color=VERM)
ax[1].legend(loc="upper left", **ps.LEGEND)

ps.save(fig, os.path.join(HERE, "example.pdf"))
ps.report(lock_states=f"{ms[0]}..{ms[-1]}", lock_T=f"{Ts[0]}..{Ts[-1]}",
          last_ratio=f"{ratio:.3f}",
          above_cubic=f"{Ts[-1] / (T0 * (ms[-1] / m0) ** 3):.1f}x",
          cycle_T=f"{cT[0]}..{cT[-1]}", cycle_BH=sorted(set(cBH)))
