---
topic_number: 7
topic_name: Alternating Current
page_range: 355-374
source_markdown: Mathpix_Cache\10 PHYSICS FOUNDATION_mathpix.md
md_kind: combined
lines: 20097-21174
---

## 7. Alternating Current
Foundation
## ALTERNATING CURRENT (A.C.)
An alternating current is one which periodically changes in magnitude and direction. It increases from zero to a maximum value, then decreases to zero and reverses in direction, increases to a maximum in this direction and then decreases to zero.
The alternating currents change both in magnitude and direction periodically. They have the various different waveforms, or waveshapes, e.g., sinusoidal, square, triangular, sawtoothed, and so on, depending on their applications.
The alternating currents, in the normal use, have the sinusoidal waveform and represented analytically as
$$
i=I_{0} \sin (\omega t)
$$
where $i$ is the instantaneous value, $I_{0}$ is the peak value, or amplitude, $\omega=2 \pi / T=2 \pi f$ is the angular frequency, $T$ being the time period and $f$ being the frequency, and $\omega t$ is the phase angle.
Fig. 7.1
Fig 7.2
The alternating currents are generated in the circuits energised by the sources of alternating e.m.f., or voltage, such as, the ac generators and electronic oscillators, represented graphically by the symbol
The sinusoidal e.m.fs, or voltages, are represented analytically as
$$
V=V_{0} \sin (\omega t)
$$
where V is the instantaneous value, $\mathrm{V}_{0}$ is the peak value, or amplitude, and $\omega=2 \pi / \mathrm{T}=2 \pi \mathrm{f}$ is the angular frequency, T being the time period and $f$ being the frequency, and $\omega t$ is the phase angle.
## ADVANTAGES OF A.C. OVER D.C.
(i) The generation of A.C. is cheaper than that of D.C.
(ii) Alternating voltage can be easily stepped up or stepped down by using a transformer.
(iii) A.C. can be easily converted into D.C. by rectifier.
(iv) It can be transmitted to a long distance without appreciable loss.
## AVERAGE OR MEAN VALUE OF ALTERNATING CURRENT
The average or mean value of sinusoidal current $i=I_{0} \sin (\omega t)$ over a complete cycle is
$$
\begin{aligned}
I_{a v} & =\frac{1}{T} \int_{0}^{T} i d t=\frac{1}{T} \int_{0}^{T} I_{0} \sin (\omega t) d t=\frac{1}{T}\left[\frac{-I_{0} \cos (\omega t)}{w}\right]_{0}^{T} \frac{1}{T}\left[\frac{-I_{0} \cos (\omega t)}{w}\right]_{0}^{T} \\
& =\frac{1}{T}\left[\frac{-I_{0} \cos (2 \pi)}{\omega}+\frac{I_{0} \cos (0)}{\omega}\right]=0
\end{aligned}
$$
It is zero because the integral represents the area between the curve and time axis over a complete cycle and this area is negative as much as it positive. This is the reason that if a sinusoidal current is sent through a moving-coil galvanometer, it reads zero. The non-zero average, or mean, value of sinusoidal current $i=I_{0} \sin (\omega t)$ over a half-cycle is
$$
\begin{aligned}
& I_{a v}=\frac{2}{T} \int_{0}^{T / 2} i d t=\frac{2}{T} \int_{0}^{T / 2} I_{0} \sin (\omega t) d t=\frac{2}{T}\left[\frac{-I_{0} \cos (\omega t)}{\omega}\right]_{0}^{T / 2} \\
& =\frac{2}{T}\left[\frac{-I_{0} \cos \pi}{\omega}+\frac{I_{0} \cos (0)}{\omega}\right]=\frac{2 I_{0}}{\pi} \approx 0.637 I_{0}
\end{aligned}
$$
This average value is the height of rectangle, shown shaded in the figure, having its area equal to the area under one loop of the sine curve.
Similarly, the non-zero average, or mean, value of sinusoidal e.m.f., or voltage, $v=V_{0} \sin (\omega t)$ over a half cycle is
$$
V_{a v}=\frac{2 V_{0}}{\pi} \approx 0.637 V_{0}
$$
Fig. 7.3
## ROOT-MEAN SQUARE (RMS) VALUE OF ALTERNATING CURRENT
Most of the ac meters are calibrated to record not the peak value of alternating current, or voltage, but the root-mean-square (rms) value, i.e., the square root of the average, or mean, of the square of current, or voltage. Because $i^{2}$ is always positive and the graph of $i^{2}$ against the time $t$ lies above the $t$-axis, as shown, the average of $i^{2}$ is never zero, even when the average of $i$ itself is zero. The average value of $i^{2}$, called the mean square current, over a complete cycle is
$$
\begin{aligned}
I_{\mathrm{rms}}= & I^{2}=\frac{1}{T} \int_{0}^{T} i^{2} d t=\frac{1}{T} \int_{0}^{T} I_{0}^{2} \sin ^{2}(\omega t) d t=\frac{1}{T} \int_{0}^{T} \frac{I_{0}^{2}}{2}[1-\cos (2 \omega t)] d t \\
& =\frac{I_{0}^{2}}{2 T}\left[t-\frac{\sin (2 \omega t)}{2 \omega}\right]_{0}^{T}=\frac{I_{0}^{2}}{2 T}\left[T-\frac{\sin (4 \pi)}{2 \omega}+\frac{\sin (0)}{2 \omega}\right]=\frac{I_{0}^{2}}{2}
\end{aligned}
$$
which is the height of rectangle, shown shaded in the figure.
Its square root gives the root-mean-square (rms) current,
$$
\text { i.e., } I_{\mathrm{rms}} \equiv I=\frac{I_{0}}{\sqrt{2}} \approx 0.707 I_{0}
$$
Similarly, the root-mean-square (rms) value of a sinusoidal voltage
$$
V_{\mathrm{rms}} \equiv V=\frac{V_{0}}{\sqrt{2}} \approx 0.707 V_{0}
$$
When a sinusoidal current $i=I_{0} \sin (\omega t)$ flows through a resistance $R$, the average rate of heating during a complete cycle is given by
$$
P=\frac{1}{T} \int_{0}^{T} i^{2} R d t=R\left[\frac{1}{T} \int_{0}^{T} i^{2} d t\right]=R\left(I_{\mathrm{rms}}\right)^{2}
$$
which also equals the rate of heating, when a dc of the value $I_{\mathrm{rms}}$ flows through the same resistance $R$.
For this reason, $I_{\mathrm{rms}}$ is also called the effective value, or virtual value, or dc value of ac.
The currents and voltages in the power distribution systems are always quoted in terms of their rms values. Thus, when we speak of our house-hold power supply as ' 220 V ac', we mean to say that the rms voltage is 220 V . Then, the peak voltage is
$$
V_{0}=\sqrt{2} V_{\mathrm{rms}}=\sqrt{2} \times 220 \approx 311 V
$$
i.e., the voltage varies between +311 V and -311 V in a complete cycle. For the reason, an ac of 220 V is more dangerous than a dc of 220 V .
If a domestic appliance draws 2.5 A from a $220-\mathrm{V}, 60-\mathrm{Hz}$ power supply, find
(a) the average current
(b) the average of the square of the current
(c) the current amplitude
(d) the supply voltage amplitude.
## SOLUTION
(a) The average of sinusoidal AC values over any whole number of cycles is zero.
(b) RMS value of current $=\mathrm{I}_{\mathrm{rms}}=2.5 \mathrm{~A}$
$\therefore \quad\left(I^{2}\right)_{a v}=\left(I_{r m s}\right)^{2}=6.25 A^{2}$
(c) $I_{r m s}=\frac{I_{m}}{\sqrt{2}}$
∴ Current amplitude $=\sqrt{2} I_{\text {rms }}=\sqrt{2}(2.5 A)=3.5 \mathrm{~A}$
(d) $V_{r m s}=220 \mathrm{~V}=\frac{V_{m}}{\sqrt{2}}$
∴ Supply voltage amplitude $V_{m}=\sqrt{2}\left(V_{r m s}\right)=\sqrt{2}(220 \mathrm{~V})=311 \mathrm{~V}$.
## ILLUSTRATION : 7.1
What is the ratio of mean value over half cycle to r.m.s. value of A.C.?
## SOLUTION :
We know that $\mathrm{I}_{r m s}=\mathrm{I}_{0} / \sqrt{2}$ and $\mathrm{I}_{m}=2 \mathrm{I}_{0} / \pi$
$\therefore \frac{\mathrm{I}_{m}}{\mathrm{I}_{r m s}}=\frac{2 \sqrt{2}}{\pi}$
## Learn More
(i) Time period : The time taken by A.C. to go through one cycle of changes is called its time period. It is given as $\mathrm{T}=\frac{2 \pi}{\omega}$
(ii) Phase : Phase is that property of wave motion which tells us the position of the particle at any instant as well as its direction of motion. It is measured either by the angle which the particle makes with the mean position or by fraction of time period.
(iii) Phase angle : angle associated with the wave motion (sine or cosine) is called phase angle.
(iv) Lead : Out of the current and e.m.f the one having greater phase angle will lead the other e.g. in equation $i=i_{0} \sin \omega \mathrm{t}+\frac{\pi}{2}$ and $e=e_{0} \sin \omega \mathrm{t}$, the current leads the e.m.f. by an angle $\frac{\pi}{2}$.
(v) Lag : Out of current and e.m.f. the one having smaller phase angle will lag the other. In the above equations, the e.m.f lags the current by $\frac{\pi}{2}$.
## RESISTANCE OFFERED BY VARIOUS ELEMENTS (RESISTOR, INDUCTOR, CAPACITOR) TO A.C.
Alternating current in a circuit may be controlled by resistance, inductance and capacitance, while the direct current is controlled only by resistance.
(i) Impedance ( $\mathbf{Z}$ ) : In alternating current circuit, the ratio of e.m.f. applied and consequent current produced is called the impedance and is denoted by Z, i.e., $\left[Z=\frac{E}{I}=\frac{E_{0}}{I_{0}}=\frac{E_{r m s}}{I_{r m s}}\right]$
Physically impedance of ac circuit is the hindrance offered by resistance alongwith either inductance or capacitance or both in the circuit to the flow of ac through it. Its S.I.unit is ohm.
(ii) Reactance (X) : The hindrance offered by inductance or capacitance or both to the flow of ac in an ac circuit is called reactance and is denoted by X . Thus when there is no ohmic resitance in the cirucit, the reactance is equal to impedance. The reactance due to inductance alone is called inductive reactance and is denoted by $\mathrm{X}_{\mathrm{L}}$, while the reactance due to capacitance alone is called the capacitive reactance and is denoted by $\mathrm{X}_{\mathrm{C}}$. Its $\mathbf{S}$.I.unit is also ohm.
(iii) Admittance. The inverse of impedance is called the admittance and is denoted by Y , i.e., $\mathrm{Y}=\frac{1}{Z}$ Its S.I.unit is ohm ${ }^{-1}$.
## IMPEDANCES AND PHASES OF AC CIRCUIT CONTAINING DIFFERENT ELEMENTS
As already pointed out that in an ac circuit the current and applied e.m.f.'s are not necessarily in same phase. The applied e.m.f. (E) and current produced ( $I$ ) may be expresed as
$\mathrm{E}=\mathrm{E}_{0} \sin \omega \mathrm{t}$ and $\mathrm{I}=\mathrm{I}_{0} \sin (\omega \mathrm{t}+\phi)$ with $\mathrm{I}_{0}=\mathrm{E}_{0} / \mathrm{Z}$
where $E_{0}$ and $I_{0}$ are peak values of alternating e.m.f. and current.
(i) Circuit containing only resitance (R): Consider a pure ohmic resistor (zero inductance) of resistance R connected to an alternating source of e.m.f. $\mathrm{E}=\mathrm{E}_{0} \sin \omega$ t. Then current I in the circuit is
Fig. 7.5
Comparing this with standard equation, we note that
Impedance of circuit, $\mathrm{Z}=\mathrm{R}$ and phase difference between current and e.m.f. $=0$.
Hence we conclude that in a purely resistive ac circuit the current and voltage are in same phase and impedance of circuit is equal to the ohmic resistance.
(ii) Circuit contianing only inductance(L): Consider a pure inductor (zero ohmic resistance) of inductance L connected to an alternating source of e.m.f. $\mathrm{E}=\mathrm{E}_{0} \sin \omega$ t. Then current I in the circuit is
$$
\mathrm{I}=\mathrm{I}_{0} \sin \left(\omega t-\frac{\pi}{2}\right) \text { where } \mathrm{I}_{0}=\frac{E_{0}}{\omega L}
$$
Fig. 7.6
Comparing this with standard equation, we know that $\mathrm{Z}=\omega \mathrm{L}$ and $\phi=\pi / 2$.
Hence we conclude that in a purely inductive circuit the current lags behind the applied voltage by an angle $\pi / 2$ and the impedance to the circuit is $\omega L$ and this is called as inductive reactance.
## Physics
Fig. 7.7
(iii) Circuit containing only capacitance(C): Consider a capacitor of capacitance C connected to an alternating source of e.m.f.,
$$
\mathrm{E}=\mathrm{E}_{0} \sin \omega \mathrm{t}
$$
Then the current through C is given by, $\mathrm{I}=\mathrm{I}_{0} \sin \left(\omega t+\frac{\pi}{2}\right)$
Comparing this with standard equation, we find that $\mathrm{X}_{\mathrm{C}}=1 / \omega \mathrm{C}$ and $\phi=+\pi / 2$
Fig. 7.8
Hence we conclude that in a purely capacitive circuit the current leads the applied e.m.f. by an angle $\pi / 2$ and the impedance of the circuit is $1 / \omega \mathrm{C}$ and this is known as capacitive reactance $\mathrm{Z}=\mathrm{X}_{\mathrm{C}}=\frac{1}{\omega \mathrm{C}}$.
Fig. 7.9
## CIRCUIT CONTAINING RESISTANCE, INDUCTANCE AND CAPACITANCE IN SERIES (SERIES LCR CIRCUIT)
Consider a circuit containing a resistance R , inductance L and capacitance C in series having an alternating e.m.f. $\mathrm{E}=\mathrm{E}_{0} \sin \omega \mathrm{t}$. Let $\mathbf{I}$ be the current flowing in circuit. $V_{R}, V_{L}$ and $V_{C}$ are respective potential differences across resistance R , inductance L and capacitance C .
Fig. 7.10
The p.d. $\mathrm{V}_{\mathrm{R}}$ is in phase with current $\mathbf{I}$. The p.d. $V_{C}$ lags behind the current by angle $\pi / 2$. The p.d. $V_{L}$ leads the current by angle $\pi / 2$.
∴ Resultant applied e.m.f., $E=\sqrt{\left[V_{R}^{2}+\left(V_{C}-V_{L}\right)^{2}\right]}$
i.e., $\mathrm{E}=\sqrt{\left\{(\mathrm{R} \mathbf{I})^{2}+\left(\mathbf{I} \mathrm{X}_{\mathrm{C}}-\mathbf{I} \mathrm{X}_{\mathrm{L}}\right)^{2}\right\}}$
∴ Impedance, $Z=\frac{E}{\mathrm{I}}=\sqrt{\left\{R^{2}+\left(X_{C}-X_{L}\right)^{2}\right\}}$
The phase leads of current over applied e.m.f. is given by
$\tan \phi=\frac{V_{C}-V_{L}}{V_{R}}=\frac{I X_{C}-I X_{L}}{R I}=\frac{X_{C}-X_{L}}{R}$
Fig. 7.11
It is concluded that
(a) If $X_{C}>X_{L}$, the value of $\phi$ is positive, i.e., current leads the applied e.m.f..
(b) If $X_{C}<X_{L}$, the value of $\phi$ is negative, i.e., current lags behind the applied e.m.f..
(c) If $X_{C}=X_{L}$, the value of $\phi$ is zero, i.e., current and e.m.f. are in same phase. This is called the case of resonance and resonant frequency for condition $\mathrm{X}_{\mathrm{C}}=\mathrm{X}_{\mathrm{L}}$, is given by
$$
\begin{aligned}
& \frac{1}{\omega \mathrm{C}}=\omega \mathrm{L} \text { i.e., } \omega=\frac{1}{\sqrt{\mathrm{LC}}} \\
& \therefore f_{o}=\omega / 2 \pi=\frac{1}{2 \pi \sqrt{(L C)}}
\end{aligned}
$$
Fig. 7.12
Thus the resonant frequency depends on the product of $L$ and $C$ and is independent of R .
At resonance, impedance is minimum, $Z_{\text {min }}=\mathrm{R}$ and current is maximum $I_{\text {max }}=\frac{E}{Z_{\text {min }}}=\frac{E}{R}$
## Learn More
## Quality factor or Q-factor
The characteristics of a series resonant circuit is determined by the $Q$-factor of the circuit. It can be defined as
$$
\begin{aligned}
Q \text {-factor } & =2 \pi \frac{\text { maximum energy stored }}{\text { energy dissipated per cycle }} \\
& =\frac{\text { Resonance frequency }}{\text { band width }}=\frac{\omega_{0}}{\Delta \omega} \\
& =\frac{\sqrt{\frac{1}{L C}}}{\left(\frac{R}{L}\right)} \\
Q \text {-factor } & =\frac{1}{R} \sqrt{\frac{L}{C}}
\end{aligned}
$$
Fig. 7.13
## Physics
## ILLUSTRATIOM : 7.2
Obtain the resonant frequency $\omega_{r}$ of a series $L C R$ circuit with $L=2.0 H, C=32 \mu F$ and $R=10 \Omega$. What is the $Q$-value of this circuit?
## SOLUTION :
Given, $\mathrm{L}=2 \mathrm{H}, \mathrm{C}=32 \mu \mathrm{~F}=32 \times 10^{-6} \mathrm{~F}, \quad \mathrm{R}=10 \Omega, \omega_{\mathrm{r}}=?, \mathrm{Q}=?$
By relation,
By relation,
$\omega_{\mathrm{r}}=\frac{1}{\sqrt{\mathrm{LC}}}=\frac{1}{\sqrt{2 \times 32 \times 10^{-6}}}=\frac{10^{3}}{8}=125 \mathrm{rad} \mathrm{s}^{-1}$.
Quality factor (Q-value) $\frac{\omega_{r} L}{R}=\frac{125 \times 2}{10}=25$
## RESONANCE
When the impedance of the circuit is maximum i.e., $Z=R$ or admittance of the circuit becomes minimum $\left(Y=G=\frac{1}{R}\right)$ condition of resonance occurs in parallel resonance circuit.
In this condition $X_{L}=X_{C}$
or $\quad \omega_{\mathrm{r}}=\frac{1}{\sqrt{\mathrm{LC}}} ; \mathrm{f}_{\mathrm{r}}=\frac{1}{2 \pi \sqrt{\mathrm{LC}}}$
In parallel circuit at resonance :
- $\mathrm{I}_{\mathrm{OL}}=\mathrm{I}_{\mathrm{OC}}$, the phase $\phi=0^{\circ}, \cos \phi=1$
- The peak current is minimum
- The quality factor $\mathrm{Q}=\frac{\mathrm{R}}{\omega_{\mathrm{r}} \mathrm{L}}$
- The bandwidth $\mathrm{BW}=\frac{\mathrm{f}_{\mathrm{r}}}{\mathrm{Q}}$
## Learn More
## Practical LCR Parallel Resonant Circuit
The inductance coil has some resistance R and it is connected in parallel to a capacitor C .
For this circuit, the impedance is obtained from $\frac{1}{\mathrm{Z}}=\mathrm{Y}$,
where the admittance is $Y=\sqrt{\frac{\left(1-\omega^{2} L C\right)^{2}+(\omega C R)^{2}}{R^{2}+(\omega L)^{2}}}$
The resonance occurs when the admittance is minimum.
Resonance frequency $\omega_{\mathrm{r}}=\frac{1}{\sqrt{\mathrm{LC}}}\left(1-\frac{\mathrm{R}^{2} \mathrm{C}}{\mathrm{L}}\right)^{1 / 2}$
or $\quad \omega_{\mathrm{r}}=\sqrt{\frac{1}{\mathrm{LC}}-\frac{\mathrm{R}^{2}}{\mathrm{~L}^{2}}} \quad$ or, $\quad f_{r}=\frac{1}{2 \pi} \sqrt{\frac{1}{L C}-\frac{R^{2}}{L^{2}}}$
If $\mathrm{R}=0$ in fig. then it becomes a parallel LC circuit.
Resonance occurs at $\omega_{\mathrm{r}}=\frac{1}{\sqrt{\mathrm{LC}}} ; \mathrm{f}_{\mathrm{r}}=\frac{1}{2 \pi \sqrt{\mathrm{LC}}}$
Fig. 7.15
If $\frac{1}{\mathrm{LC}}-\frac{\mathrm{R}^{2}}{\mathrm{~L}^{2}}$ has negative value then resonance does not occurs. A parallel LCR circuit offers maximum impedance at $\mathrm{f}=\mathrm{f}_{\mathrm{r}}$. The impedance decreases for $\mathrm{f}<\mathrm{f}_{\mathrm{r}}$ and $\mathrm{f}>\mathrm{f}_{\mathrm{r}}$. Since the impedance between frequencies $\mathrm{f}_{1}$ and $\mathrm{f}_{2}$ is large, current between this band is small.
The parallel LCR circuit is therefore, also called Band Rejector circuit. $\mathrm{f}_{1}$ and $\mathrm{f}_{2}$ are half power frequencies and impedance in between these two is $\frac{\mathrm{Z} \geq \mathrm{Z}_{\max }}{\sqrt{2}}$.
Before resonance the current leads the applied e.m.f., at resonance it is in phase, and after resonance it lags behind the e.m.f.. LCR series circuit is also called as acceptor circuit and parallel LCR circuit is called rejector circuit.
## Choke Coil
A choke coil is simply an inductor with a large self-inductance and negligible resistance (zero in ideal case). It is used in A.C. circuits for reducing current without consuming power.
The choke coil is put in series with the electrical device, such as fluorescent tube requiring a low value of current. The inductive reactance decreases the current. Since the alternating e.m.f. leads the current by phase angle $\frac{\pi}{2}$.
The average power consumed by the choke coil $P_{a v}=E_{v} I_{v} \cos \frac{\pi}{2}=0$.
However, a practical inductance possesses a small resistance i.e., a practical inductance may be treated as a series combination of inductance $L$ and a small resistance $r$.
Average power consumed in a practical inductance $P_{a v}=E_{v} I_{v} \times \frac{r}{\sqrt{r^{2}+\omega^{2} L^{2}}}$
For practical inductance power factor $(\cos \phi)=\frac{r}{\sqrt{r^{2}+\omega^{2} L^{2}}}$
Uses : In a.c. circuits, a choke coil is used to control the current in place of a resistance. If a resistance is used to control the current, the electrical energy will be wasted in the form of heat. A choke coil decreases the current without wasting electrical energy in the form of heat.
## TRANSFORMER
It is a device used for transforming a low alternating voltage of high current into a high alternating voltage of low current and vice versa, without increasing power or changing frequency.
Principle : It works on the phenomenon of mutual induction.
Construction: It has three main parts described below:
1. Laminated core C: It is of sand-mixed iron in shell type, it has more resistance due to laminations and mixing of sand. It is done to reduce eddy current in the core and minimize its heating.
2. Primary coil P : It is a coil of enamelled copper wire wrapped over the central arm of the core and is insulated by varnish.
3. Secondary coil S : It is also a coil of enamelled copper wire. It is wrapped over the primary coil and insulated by wax paper. Transformed alternating voltage is obtained from it. It forms output section of the transformer.
If a low voltage is to be transformed into a high voltage, then the number of turns in secondary is more than those in primary.
The transformer is called a step up transformer.
If a high voltage is to be transformed into a low voltage, then the number of turns in secondary is less than those in primary.
The transformer is called a step-down transformer.
Transformation ratio of the transformer,
$$
\begin{aligned}
& K=\frac{\text { Number of turns in } \sec \text { ondary }\left(N_{s}\right)}{\text { Number of turns in primary }\left(N_{p}\right)} \\
& K>1, \text { for step-up transformer. } \\
& K<1, \text { for step-down transformer. }
\end{aligned}
$$
The whole arrangement is kept immersed in a special oil called transformer oil, taken in metallic cans. The oil provides insulation as well as cooling.
Working : As voltage applied to the primary is alternating, it produces a continuous change in magnetic flux in primary as well as in secondary. Due to mutual induction, an e.m.f. is induced in secondary. It is higher or lower than that induce in primary depending upon whether the transformer is a step-up or step-down transformer. The induced e.m.f. in secondary gives output voltage.
Theory : An alternating e.m.f. $\mathrm{E}_{\mathrm{p}}$ is applied across the primary which produces current $\mathrm{I}_{\mathrm{p}}$ in the primary circuit and a current $\mathrm{I}_{\mathrm{s}}$ in the secondary circuit. The currents in the coils produce a magnetization in the soft-iron core and there is a corresponding magnetic field B inside the core. The field due to magnetization of the core is large as compared to the field due to the current in the coils. We assume that the field is constant in magnitude everywhere in the core and hence, its flux (BA) through each turn is same for the primary as well as for the secondary coil.
Let the flux through each turn be $\Phi$.
The emf induced in the primary, $E_{P}=-N_{p} \frac{d \Phi}{d t}$
and induced emf in the secondary, $\mathrm{E}_{\mathrm{S}}=-\mathrm{N}_{\mathrm{s}} \times \frac{\mathrm{d} \Phi}{\mathrm{dt}}$
If we neglect the resistance in the primary circuit, Kirchhoff's loop law applied to the primary circuit which gives,
$$
\begin{gathered}
E_{p}=N_{p} \frac{d \Phi}{d t} \\
\text { Also, } E_{s}=-N_{s} \frac{d \Phi}{d t}
\end{gathered}
$$
From eqs. (i) and (ii), $\quad \mathrm{E}_{\mathrm{s}}=-\frac{\mathrm{N}_{\mathrm{s}}}{\mathrm{N}_{\mathrm{p}}} \mathrm{E}_{\mathrm{p}}$
The minus sign shows that $\mathrm{E}_{\mathrm{s}}$ is $180^{\circ}$ out of phase with $\mathrm{E}_{\mathrm{p}}$.
Equns. (i) and (ii) are valid for all values of currents in the primary and the secondary circuits. If there is no loss of power in output and input circuit then, input power = output power
i.e., $E_{p} \times I_{p}=E_{s} \times I_{s} \quad$ or, $\frac{I_{p}}{I_{s}}=\frac{E_{s}}{E_{p}}=\frac{N_{s}}{N_{p}}$
But in practice there is always energy loss so, input power > output power.
Hence, $\mathrm{E}_{\mathrm{p}} \times \mathrm{I}_{\mathrm{p}}>\mathrm{E}_{\mathrm{s}} \times \mathrm{I}_{\mathrm{s}}$
## Energy loss in a transformer :
(i) Copper loss : Energy lost in winding of the transformer is known as copper loss. Primary and secondary coils of a transformer are generally made of copper wires. These copper wires have resistance (R). When current (I) flows through these wires, power loss ( $\mathrm{I}^{2} \mathrm{R}$ ) takes place. This loss appears as the heat produced in the primary and secondary coils. Copper loss can be reduced by using thick wires for the windings.
(ii) Flux loss : In actual transformer, the coupling between primary and secondary coil is not perfect. It means that magnetic flux linked with the primary coil is not equal to the magnetic flux linked with secondary coil, so a certain amount of electric energy supplied to the primary coil is wasted.
(iii) Eddy current loss : When a changing magnetics flux links with the iron core of the transformer, eddy currents are set up. These eddy currents produce heat which leads to the wastage of energy. This energy loss is reduced by using laminated core.
Eddy currents are reduced in a laminated core because their paths are broken as compared to solid core as shown in figure.
Fig. 7.17
(iv) Hysteresis loss : When alternating current passes through the primary coil, core of the transformer is magnetized and demagnetised over a complete cycle. Some energy is lost in magnetising and de-magnetising the iron core. The energy loss in a complete cycle is equal to area of the hysteresis loop.
This energy loss can be minimized by using suitable material having narrow hysteresis loop for the core of a transformer.
(v) Loss due to vibration of core or humming loss : A transformer produces humming noise due to magnetostriction effect. Some electrical energy is lost in the form of mechanical energy to produce vibration in the core.
## Efficiency of a Transformer
In an ordinary transformer, there is some loss of energy due to coil resistance, hysteresis in the core, eddy currents in the core etc. The percentage efficiency of a transformer is defined as
i.e., $\eta \%=\frac{\text { Output power }}{\text { Input power }} \times 100=\frac{V_{S} I_{S}}{V_{P} I_{P}} \times 100$
Efficiency for an ideal transformer is 100\% but of practical transformer lies between $70 \%-90 \%$.
A.C. equipments such as electric motors are more durable and convenient compared to D.C. equipments.
## Uses of Transformer
A transformer is used in almost all ac operation.
(i) In voltage regulators for TV, refrigerator, computer, air conditioner etc.
(ii) In the induction furnaces.
(iii) Step down transformer is used for welding purposes.
(iv) In the transmission of ac over long distance.
(v) Step down and step up transformers are used in electrical power distribution.
Fig. 7.18
(vi) Audio frequency transformers are used in radiography, television, radio, telephone etc.
(vii) Radio frequency transformers are used in radio communication.
The ease with which voltages can be stepped UP or down with a transformer is the principal reason that most electric power is AC rather then DC
Fig. 7.19 Voltage generated in power stations is stepped up with transformers prior to being transferred across country by overhead cables. Then other transformers reduce the voltage before supplying it to homes, offices, and factories.
A lossless transformer steps down 220 V to 22 V and operates a device having an impedance of $220 \Omega$. What is the primary current?
## SOLUTION
In the lossless transformer, we are given that
$\mathrm{V}_{\mathrm{P}}=220 \mathrm{~V}, \mathrm{~V}_{\mathrm{S}}=22 \mathrm{~V}, \mathrm{I}_{\mathrm{S}}=\frac{V_{s}}{R}=\frac{22}{220}=0.1 \mathrm{~A}: \mathrm{I}_{\mathrm{p}}=?$
$\frac{\mathrm{V}_{\mathrm{S}}}{\mathrm{V}_{\mathrm{P}}}=\frac{\mathrm{I}_{\mathrm{P}}}{\mathrm{I}_{\mathrm{S}}} \Rightarrow \frac{22}{220}=\frac{\mathrm{I}_{\mathrm{P}}}{0.1} \Rightarrow \mathrm{I}_{\mathrm{P}}=0.01 \mathrm{~A}$
## აગ!აჩყᲫ
## ILLUSTRATIOM : 7.3
In a transformer, the primary and secondary have 1000 and 3000 turns, respectively. If the primary is connected across an ac source of 80 V , then what will be the voltage across each turn of the secondary?
## SOLUTION :
Given: $\mathrm{N}_{\mathrm{p}}=1000 ; \mathrm{N}_{\mathrm{s}}=3000 \quad \mathrm{~V}_{\mathrm{p}} 80 \mathrm{v} ; \mathrm{V}_{\mathrm{s}}=$ ?
In the transformer, we have
$\frac{\mathrm{V}_{\mathrm{S}}}{\mathrm{V}_{\mathrm{P}}}=\frac{\mathrm{N}_{\mathrm{S}}}{\mathrm{N}_{\mathrm{P}}} \Rightarrow \frac{\mathrm{V}_{\mathrm{S}}}{80}=\frac{3000}{1000} \Rightarrow \mathrm{~V}_{\mathrm{S}}=240 \mathrm{~V}$
and then, the voltage across each turn of secondary becomes $\frac{\mathrm{V}_{\mathrm{S}}}{\mathrm{N}_{\mathrm{S}}}=\frac{240}{3,000}=0.08 \mathrm{~V}$
## ILLUSTRATIOM : 7.4
A transformer is used to step-down a voltage from 220 V to 11 V . If the primary and secondary currents are 5 A and 90 A , respectively, what is the efficiency of transformer?
## SOLUTION :
Here, $\mathrm{V}_{\mathrm{p}}=220 \mathrm{~V} ; \mathrm{V}_{\mathrm{S}}=11 \mathrm{~V} \mathrm{I}_{\mathrm{p}}=5 \mathrm{~A} ; \mathrm{I}_{2}=90 \mathrm{~A}$
The efficiency of transformer
$$
\eta=\frac{V_{S} I_{S}}{V_{P} I_{P}} \times 100 \%=\frac{11 \times 90}{220 \times 5} \times 100 \%=90 \%
$$
## MISCELLANEOUS SOLVED EXAMPLES
1. A current of 4 A flows in a coil when connected to a 12 V dc source. If the same coil is connected to a $12 \mathrm{~V}, 50 \mathrm{rad} / \mathrm{s}$ a.c. source, a current of 2.4 A flows in the circuit. Determine the inductance of the coil.
Sol. A coil consists of an inductance (L) and a resistance (R).
In dc only resistance is effective. Hence,
$$
\mathrm{R}=\frac{\mathrm{V}}{\mathrm{i}}=\frac{12}{4}=3 \Omega
$$
In $\mathrm{ac}, \mathrm{i}_{\text {rms }}=\frac{\mathrm{V}_{\text {rms }}}{\mathrm{Z}}=\frac{\mathrm{V}_{\text {rms }}}{\sqrt{\mathrm{R}^{2}+\omega^{2} \mathrm{~L}^{2}}} \quad \therefore \mathrm{~L}^{2}=\frac{1}{\omega^{2}}\left[\left(\frac{\mathrm{~V}_{\text {rms }}}{\mathrm{i}_{\text {rms }}}\right)^{2}-\mathrm{R}^{2}\right]$
$\Rightarrow \mathrm{L}=\frac{1}{\omega} \sqrt{\left(\frac{\mathrm{~V}_{\mathrm{rms}}}{\mathrm{i}_{\mathrm{rms}}}\right)^{2}-\mathrm{R}^{2}}=\frac{1}{50} \sqrt{\left(\frac{12}{2.4}\right)^{2}-(3)^{2}}=0.08$ henry
2. When a series combination of inductance and resistance are connected with a $\mathbf{1 0 V}, \mathbf{5 0 H z}$ a.c. source, a current of $\mathbf{1 A}$ flows in the circuit. The voltage leads the current by a phase angle of $\pi / 3$ radian. Calculate the values of resistance and inductive reactance.
Sol. As we know, $\mathrm{Z}=\sqrt{\mathrm{R}^{2}+\mathrm{X}_{\mathrm{L}}^{2}}=\frac{\mathrm{E}}{\mathrm{I}}=\frac{10}{1}=10 \Omega$
$\frac{\mathrm{X}_{\mathrm{L}}}{\mathrm{R}}=\tan \phi=\tan \frac{\pi}{3}=\sqrt{3} \Rightarrow \mathrm{X}_{\mathrm{L}}=\sqrt{3} \mathrm{R}$
$Z=\sqrt{R^{2}+3 R^{2}}=10 \Rightarrow 2 R=10 \Rightarrow R=5 \Omega$ and $X_{L}=\sqrt{3} R=5 \sqrt{3} \Omega$
3. For a series $L C R$ circuit $I=100 \sin (100 \pi t-\pi / 3) \mathrm{mA}$ and $V=100 \sin (100 \pi t)$ volt, then
(a) calculate resistance and reactance of circuit.
(b) find average power loss.
Sol. (a) Impedance, $\mathrm{Z}=\frac{\mathrm{V}_{0}}{\mathrm{I}_{0}}=\frac{100}{100 \times 10^{-3}}=1000 \Omega$
Resistance, $\mathrm{R}=\mathrm{Z} \cos \phi=1000 \cos \left(\frac{\pi}{3}\right)=500 \mathrm{ohm}$
Reactance, $\mathrm{X}=\mathrm{Z} \sin \phi=1000 \sin \left(\frac{\pi}{3}\right)=500 \sqrt{3} \mathrm{ohm}$
(b) Average power loss, $\mathrm{P}_{\mathrm{av}}=\mathrm{V}_{\mathrm{rms}} \mathrm{I}_{\mathrm{rms}} \cos \phi$
$$
=\frac{100}{\sqrt{2}} \times \frac{100}{\sqrt{2} \times 1000} \times \cos \left(\frac{\pi}{3}\right)=5 \times \frac{1}{2}=2.5 \text { watts }
$$
4. A R-L circuit draws a power of 440 W from a source of $220 \mathrm{~V}, 50 \mathrm{~Hz}$. The power factor of the circuit is 0.5 . To make the power factor of the circuit as $\mathbf{1 . 0}$, what capacitance will have to be connected with it?
Sol. $\because$ Power $\mathrm{P}=\mathrm{VI} \cos \phi=\frac{\mathrm{V}^{2}}{\mathrm{Z}} \cos \phi$
$\therefore \quad \mathrm{Z}=\frac{\mathrm{V}^{2} \cos \phi}{\mathrm{P}}=\frac{(220)^{2}(0.5)}{(440)}=55 \Omega$
Also power factor
$$
\begin{aligned}
& \cos \phi=\frac{R}{Z} \Rightarrow R=Z \cos \phi=(55)(0.5)=27.5 \Omega \\
\therefore & X_{L}=\sqrt{Z^{2}-R^{2}}=\sqrt{(55)^{2}-\left(\frac{55}{2}\right)^{2}}=\frac{55 \sqrt{3}}{2} \Omega
\end{aligned}
$$
when power factor is 1.0 then $\mathrm{X}_{\mathrm{L}}=\mathrm{X}_{\mathrm{C}}$
so $\mathrm{X}_{\mathrm{L}}=\frac{1}{\omega \mathrm{C}} \Rightarrow \mathrm{C}=\frac{1}{\omega \mathrm{X}_{\mathrm{L}}}=\frac{1}{(314)\left(\frac{55 \sqrt{3}}{2}\right)}=6.68 \times 10^{-5} \mathrm{~F}$
5. A series $L C R$ circuit with $L=0.12 H, C=480 \mathrm{nF}, R=23 \Omega$ is connected to a 230 V variable frequency supply find :
(a) Source frequency for which current is maximum.
(b) Q-factor of the given circuit.
Sol. (a) we know, $\omega=\frac{1}{\sqrt{\mathrm{LC}}}=\frac{1}{\sqrt{0.12 \times 480 \times 10^{-9}}}=\frac{10^{5}}{24} \mathrm{rad} / \mathrm{s} \Rightarrow \mathrm{f}=\frac{1}{2 \pi} \times \frac{10^{5}}{24}=6.63 \times 10^{2} \mathrm{~Hz}$
(b) Q-factor, $\frac{\mathrm{X}_{\mathrm{L}}}{\mathrm{R}}=\frac{\omega \mathrm{L}}{\mathrm{R}}=\frac{10^{5} \times 0.12}{24 \times 23}=\frac{10^{3}}{46}=21.7$
6. A variable frequency 230 V alternating voltage source is connected across a series combination of $\mathbf{L}=\mathbf{5 . 0 H}$, $\mathrm{C}=\mathbf{8 0} \mu \mathrm{F}$ and $\mathrm{R}=\mathbf{4 0} \Omega$. Calculate :
(a) The angular frequency of the source at resonance.
(b) Amplitude of current at resonance frequency.
Sol. (a) Angular frequency at resonance
$$
\omega_{\mathrm{r}}=\frac{1}{\sqrt{\mathrm{LC}}}=\frac{1}{\sqrt{5.0 \times 80 \times 10^{-6}}}=\frac{10^{2}}{2}=50 \mathrm{rad} / \mathrm{s}
$$
(b) Amplitude of current at resonance $\mathrm{I}_{\mathrm{m}}=\frac{\mathrm{V}}{\mathrm{R}}=\frac{230 \sqrt{2}}{40}=8.13 \mathrm{~A}$
7. A transformer having efficiency $90 \%$ is working on 100 V and at 2.0 kW power. If the current in the secondary coil is 5 A , calculate (i) the current in the primary and (ii) voltage across the secondary coil.
Sol. Here, $\eta=90 \%=\frac{9}{10}, I_{s}=5 \mathrm{~A}, E_{\mathrm{p}}=100 \mathrm{~V}$.
$\mathrm{E}_{\mathrm{p}} \mathrm{I}_{\mathrm{p}}=2 \mathrm{~kW}=2000 \mathrm{~W}$
(i) $\mathrm{E}_{\mathrm{p}} \mathrm{I}_{\mathrm{p}}=2000 \mathrm{~W} \quad \therefore \mathrm{I}_{\mathrm{p}}=\frac{2000}{\mathrm{E}_{\mathrm{p}}}$ or $\mathrm{I}_{\mathrm{p}}=\frac{2000}{100}=20 \mathrm{~A}$
(ii) $\eta=\frac{\text { Output power }}{\text { Input power }}=\frac{E_{S} I_{s}}{E_{p} I_{p}}$
or, $\mathrm{E}_{\mathrm{s}} \mathrm{I}_{\mathrm{s}}=\eta \times \mathrm{E}_{\mathrm{p}} \mathrm{I}_{\mathrm{p}}=\frac{9}{10} \times 2000=1800 \mathrm{~W} \quad \therefore \mathrm{E}_{\mathrm{s}}=\frac{1800}{\mathrm{I}_{\mathrm{s}}}=\frac{1800}{5}=360$ Volt
## Exercise
## Single Option Correct
DIRECTIONS (Qs. 1-32) : This section contains multiple choice questions. Each question has 4 choices (a), (b), (c) and (d) out of which only one is correct.
1. An inductor, a resistor and a capacitor are joined in series with an AC source. As the frequency of the source is slightly increased from a very low value, the reactance of the
(a) inductor increases
(b) reasistor increases
(c) capacitor increases
(d) circuit increases
2. An A.C. source is connected to a resistive circuit. What is true of the following?
(a) current leads ahead of voltage in phase
(b) current lags behind voltage in phase
(c) current and voltage are in same phase
(d) any of the above may be true depending upon the value of resistance.
3. The capacitive reactance in an A.C. circuit is
(a) effective resistance due to capacity
(b) effective wattage
(c) effective voltage
(d) none of the above
4. If instantaneous current is given by $i=4 \cos (\omega \mathrm{t}+\phi)$ amperes, then the r.m.s. value of current is
(a) 4 amperes
(b) $2 \sqrt{2}$ amperes
(c) $4 \sqrt{2}$ amperes
(d) Zero amperes
5. An electric bulb marked as $50 \mathrm{~W}-200 \mathrm{~V}$ is connected across a 100 V supply. The present power of the bulb is
(a) 37.5 W
(b) 25 W
(c) 12.5 W
(d) 10 W
6. Power factor is one for
(a) pure inductor
(b) pure capacitor
(c) pure resistor
(d) either an inductor or a capacitor.
7. Of the following about capacitive reactance which is correct
(a) the reactance of the capacitor is directly proportional to its ability to store charge
(b) capacitive reactance is inversely proportional to the frequency of the current
(c) capacitive reactance is mesured in farad
(d) the reactance of a capacitor in an A.C. circuit is similar to the resistance of a capacitor in a D.C. circuit
8. With increase in frequency of an A.C. supply, the inductive reactance
(a) decrease
(b) increases directly proportional to frequency
(c) increases as square of frequency
(d) decreases inversely with frequency
9. With increase in frequency of an A.C. supply, the impedance of an L-C-R series circuit
(a) remains constant
(b) increases
(c) decreases
(d) decreases at first, becomes minimum and then increases.
10. Alternating current can not be measured by dc ammeter because
(a) ac cannot pass through dc ammeter
(b) Average value of complete cycle is zero
(c) ac is virtual
(d) ac changes its direction
11. The transformer voltage induced in the secondary coil of a transformer is mainly due to
(a) a varying electric field
(b) a varying magnetic field
(c) the vibrations of the primary coil
(d) the iron core of the transformer
12. Eddy currents in the core of transformer can't be developed
(a) by increasing the number of turns in secondary coil
(b) by taking laminated transformer
(c) by making step down transformer
(d) by using a weak a.c. at high potential
13. The frequency of A.C. mains in India is
(a) $30 \mathrm{c} / \mathrm{s}$
(b) $50 \mathrm{c} / \mathrm{s}$
(c) $60 \mathrm{c} / \mathrm{s}$
(d) $120 \mathrm{c} / \mathrm{s}$
14. Hot wire ammeters are used for measuring
(a) A.C. only
(b) D.C. only
(c) both A.C. and D.C.
(d) none of these
15. Alternating current cannot be measured by D.C. ammeter because
(a) A.C. cannot pass through D.C. ammeter
(b) average value of current for complete cycle is zero
(c) A.C. is virtual
(d) A.C. changes its direction
16. Alternating current is converted to direct current by
(a) rectifier
(b) dynamo
(c) transformer
(d) motor
17. A transformer is employed to
(a) convert A.C. into D.C.
(b) convert D.C. into A.C.
(c) obtain a suitable A.C. voltage
(d) obtain a suitable D.C. voltage
18. To convert mechanical energy into electrical energy, one can use
(a) DC dynamo
(b) AC dynamo
(c) motor
(d) (a) \& (b)
19. The AC voltage across a resistance can be meausred using
(a) a potentiometer
(b) a hot-wire voltmeter
(c) a moving-coil galvanometer
(d) a moving-magnet galvanometer
20. A choke is preferred to a resistance for limiting current in A.C. circuit because
(a) choke is cheap
(b) there is no wastage of energy
(c) current becomes wattless
(d) current strength increases
21. A choke coil has
(a) high inductance and high resistance
(b) low inductance and low resistance
(c) high inductance and low resistance
(d) low inductance and high resistance
22. Transformers are used
(a) in DC circuit only
(b) in AC circuits only
(c) in both DC and AC circuits
(d) neither in DC nor in AC circuits
23. A rectangular coil of copper wires is rotated in a magnetic field. The direction of the induced current changes once in each
(a) two revolutions
(b) one revolution
(c) half revolution
(d) one-fourth revolution
24. An inductor $(\mathrm{L}=0.03 \mathrm{H})$ and a resistor $(\mathrm{R}=0.15 \mathrm{k} \Omega)$ are connected in series to a battery of 15 V EMF in a circuit shown below. The key $\mathrm{K}_{1}$ has been kept closed for a long time. Then at $\mathrm{t}=0, \mathrm{~K}_{1}$ is opened and key $\mathrm{K}_{2}$ is closed simultaneously. At $\mathrm{t}=1 \mathrm{~ms}$, the current in the circuit will be: $\left(\mathrm{e}^{5} \cong 150\right)$
[NTSE]
(a) 6.7 mA
(b) 0.67 mA (c) 100 mA
(d) 67 mA
25. A resistance ' $R$ ' draws power ' $P$ ' when connected to an AC source. If an inductance is now placed in series with the resistance, such that the impedance of the circuit becomes ' $Z$ ', the power drawn will be
[JSTSE]
(a) $\mathrm{P} \sqrt{\frac{\mathrm{R}}{\mathrm{Z}}}$
(b) $\mathrm{P}\left(\frac{\mathrm{R}}{\mathrm{Z}}\right)$
(c) P
(d) $\mathrm{P}\left(\frac{\mathrm{R}}{\mathrm{Z}}\right)^{2}$
26. The primary and the secondary coils of a transformer contain 10 and 100 turns, respectively. The primary coil is connected to a battery that supplies a constant voltage of 1.5 V . The voltage across the secondary coil is.
[NTSE]
(a) 1.5 V
(b) 0.15 V
(c) 0.0 V
(d) 15 V
27. An arc lamp requires a direct current of 10 A at 80 V to function. If it is connected to a $220 \mathrm{~V}(\mathrm{rms}), 50 \mathrm{~Hz} \mathrm{AC}$ supply, the series inductor needed for it to work is close to :
[NTSE]
(a) 0.044 H
(b) 0.065 H
(c) 80 H
(d) 0.08 H
28. A small signal voltage $\mathrm{V}(\mathrm{t})=\mathrm{V}_{0} \sin \omega \mathrm{t}$ is applied across an ideal capacitor $C$ :
[JSTSE]
(a) Current $\mathrm{I}(\mathrm{t})$, lags voltage $\mathrm{V}(\mathrm{t})$ by $90^{\circ}$.
(b) Over a full cycle the capacitor C does not consume any energy from the voltage source.
(c) Current I (t) is in phase with voltage V(t).
(d) Current $\mathrm{I}(\mathrm{t})$ leads voltage $\mathrm{V}(\mathrm{t})$ by $180^{\circ}$.
29. An inductor 20 mH , a capacitor $50 \mu \mathrm{~F}$ and a resistor $40 \Omega$ are connected in series across a source of emf $\mathrm{V}=10 \mathrm{sin}$ 340 t . The power loss in A.C. circuit is :
[JSTSE]
(a) 0.51 W
(b) 0.67 W
(c) 0.76 W
(d) 0.89 W
30. An inductor 20 mH , a capacitor $100 \mu \mathrm{~F}$ and a resistor $50 \Omega$ are connected in series across a source of emf, $\mathrm{V}=10 \sin 314 \mathrm{t}$. The power loss in the circuit is
[JSTSE]
(a) 0.79 W
(b) 0.43 W
(c) 1.13 W
(d) 2.74 W
31. An AC circuit has $R=100 \Omega, C=2 \mu \mathrm{~F}$ and $L=80 \mathrm{mH}$, connected in series. The quality factor of the circuit is :
[NTSE]
(a) 2
(b) 0.5
(c) 20
(d) 400
32. A $40 \mu \mathrm{~F}$ capacitor is connected to a $200 \mathrm{~V}, 50 \mathrm{~Hz}$ ac supply. The rms value of the current in the circuit is, nearly :
[JSTSE]
(a) 2.05 A
(b) 2.5 A
(c) 25.1 A
(d) 1.7 A
## One or More than One Option Correct
DIRECTIONS (Qs. 33-38): This section contains multiple choice questions. Each question has 4 choices (a), (b), (c) and (d) out of which ONE OR MORE may be correct.
33. The reactance of a circuit is zero. It is possible that the circuit contains
(a) an inductor and a capacitor
(b) an inductor but no capacitor
(c) a capacitor but no inductor
(d) neither an inductor nor a capacitor
34. In an AC series circuit, the instantaneous current is zero when the instantaneous voltage is maximum.Connected to the source may be a
(a) pure inductor
(b) pure capacitor
(c) pure resistor
(d) combination of an inductor and a capacitor
35. An inductor-coil having some resistance is connected to an AC source. Which of the following quantities have zero average value over a cycle?
(a) current
(b) induced e.m.f. in the inductor
(c) joule heat
(d) magnetic energy stored in the inductor
36. Figure shows a circuit with two resistors and an ideal inductor.
(a) The current in $R_{1}$ is zero just after closing the switch $S$.
(b) The current in $R_{1}$ is maximum just after closing the switch $S$.
(c) The current in $R_{2}$ is zero just after closing of the switch $S$.
(d) The currents in the resistors are maximum of their values a long time after closing the switch $S$.
37. $L, C$ and $R$ represent inductance, capacitance and resistance respectively. Which of the following have dimensions of frequency?
(a) $\frac{L}{C}$
(b) $\frac{1}{\sqrt{L C}}$
(c) $\frac{R}{L}$
(d) $\frac{1}{R C}$
38. In an ac circuit, the power factor
(a) Is zero when the circuit contains an ideal resistance only
(b) Is unity when the circuit contains an ideal resistance only
(c) Is zero when the circuit contains an ideal inductance only
(d) Is unity when the circuit contains an ideal inductance only
## Passage Based Questions
DIRECTIONS (Qs. 39-45): Study the given paragraph(s) and answer the following questions.
## Passage - I
One application of LRC series circuit is to high pass or low pass filters, which filter out either the low or high frequency components of a signal. A high pass filter is shown in figure, where the output voltage is taken across the LR combination, where LR combination represents an inductance coil that also has resistance due to large length of the wire in the coil.
39. Find the ratio for $\mathrm{V}_{\text {out }} / \mathrm{V}_{\mathrm{s}}$ as a function of the angular frequency $\omega$ of the source :
(a) $\sqrt{\frac{R^{2}+\omega L^{2}}{R^{2}+\left(\omega L-\frac{1}{\omega C}\right)^{2}}}$
(b) $\sqrt{\frac{R^{2}+(\omega L)^{2}}{R^{2}+\left(\omega L-\frac{1}{\omega C}\right)^{2}}}$
$$
\text { (c) } \sqrt{\frac{R^{2}+\omega^{2} L}{R^{2}+\left(\omega L-\frac{1}{\omega C}\right)^{2}}} \text { (d) } 1
$$
40. Which of the following statements is correct when $\omega$ is small, in the case of $\mathrm{V}_{\text {out }} / \mathrm{V}_{\mathrm{s}}$ ?
(a) $\omega \mathrm{RC}$
(b) $\frac{\omega R}{L}$
(c) $\omega \mathrm{RL}$
(d) $\frac{\omega R}{C}$
41. Which statement is correct in the limit of large frequency is reached? (For $\mathrm{V}_{\text {out }} / \mathrm{V}_{\mathrm{s}}$ ?)
(a) 1
(b) $\omega \mathrm{RC}$
(c) $\omega \mathrm{RL}$
(d) $\frac{\omega R}{L}$
## Passage - II
A fresh man physics lab is designed to study the transfer of electrical energy from one circuit to another by means of a magnetic field using simple transformers. Each transformer has two coils of wire electrically insulated from each other but wound around a common core of ferromagnetic material. The two wires are close together but do not touch each other. The primary coil is connected to a resistor such as a light bulb. The AC source produces an oscilating voltage and current int he primary coil that produces an oscillating magnetic field in the core material. This in turn induces an oscilating voltage and AC current in the secondary coil. Students collected the following data comparing the number of turns per coil ( N ), the voltage (V) and the current (I) in the coils of three transformeers.
| | Primary Coil | | | Secondary Coil | | |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| | $\mathrm{N}_{1}$ | $\mathrm{~V}_{1}$ | $\mathrm{I}_{1}$ | $\mathrm{~N}_{2}$ | $\mathrm{~V}_{2}$ | $\mathrm{I}_{2}$ |
| Transformer 1 | 100 | 10 V | 10 A | 200 | 20 V | 5 A |
| Transformer 2 | 100 | 10 V | 10 A | 50 | 5 V | 20 A |
| Transformer 3 | 200 | 10 V | 10 A | 100 | 5 V | 20 A |
42. The primary coil of a transformer has 100 turns and is connected to a 120 V AC source. How many turns are in the secondary coil if there is a 2400 V across it?
(a) 5
(b) 50
(c) 200
(d) 2000
43. Which of the following is a correct expression for R , the resistance of the load connected to the secondary coil?
(a) $\left(\frac{V_{1}}{I_{1}}\right)\left(\frac{N_{2}}{N_{1}}\right)$
(b) $\left(\frac{V_{1}}{I_{1}}\right)\left(\frac{N_{2}}{N_{1}}\right)^{2}$
(c) $\left(\frac{V_{1}}{I_{1}}\right)\left(\frac{N_{1}}{N_{2}}\right)$
(d) $\left(\frac{V_{1}}{I_{1}}\right)\left(\frac{N_{1}}{N_{2}}\right)^{2}$
44. The primary coil of a given transformer has $\frac{1}{3}$ as many turns as in its secondary coil. What primary current is required to provide a secondary current of 3.0 mA ?
(a) 1.0 mA
(b) 6.0 mA
(c) 9.0 mA
(d) 12.0 mA
45. A 12 V battery is used to supply 2.0 mA of current to the 300 turns in the primary coil of a given transformer. What is the current in the secondary coil if $\mathrm{N}_{2}=150$ turns?
(a) 0 A
(b) 1.0 mA
(c) 2.0 mA
(d) 4.0 A
## Assertion \& Reason
DIRECTIONS (Qs. 46-50): Each of these questions contains an Assertion followed by Reason. Read them carefully and answer the question on the basis of following options. You have to select the one that best describes the two statements.
(a) Assertion is true, Reason is true; Reason is a correct explanation for Assertion
(b) Assertion is true, Reason is true; Reason is not a correct explanation for Assertion
(c) Assertion is true, Reason is false
(d) Assertion is false, Reason is true
46. Assertion : Capacitor serves as a block for dc and offers an easy path to ac.
Reason : Capacitor reactance is inversely proportional to frequency.
47. Assertion : When capacitive reactance is smaller than the inductive reactance in LCR circuit, e.m.f. leads the current.
Reason : The phase angle is the angle between the alternating e.m.f. and alternating current of the circuit.
48. Assertion : When number of turns in a coil is doubled, coefficient of self-inductance of the coil becomes 4 times.
Reason : This is because $\mathrm{L} \propto \mathrm{N}^{2}$.
49. Assertion : A capacitor of suitable capacitance can be used in an ac circuit in place of the choke coil.
Reason : A capacitor blocks dc and allows ac only.
50. Assertion : If the frequency of alternating current in an ac circuit consisting of an inductance coil is increased then current gets decreased.
Reason : The current is inversely proportional to frequency of alternating current.
## Multiple Matching Questions
DIRECTIONS (Qs. 51) : Each question has four statements $(A, B, C$ and $D)$ given in Column I and five statements ( $p, q$, $r, s$ and t) in Column II. Any given statement in Column I can have correct matching with one or more statement(s) given in Column II. Match the entries in column I with entries in column II.
51. Consider the circuit shown in the figure. Currents in various branches of the circuit have been marked. Match the entries in Column - I to the entries in Column - II.
## Column-I
A. $I_{1}$ at $t=0$
B. $I_{2}$ at $t=\infty$
C. $I_{3}$ at $t=0$
D. $\quad I_{4}$ at $t=\infty$
| | A | B | C | D |
| :--- | :--- | :--- | :--- | :--- |
| (a) | s, r | r, p | q | q |
| (b) | $r$ | $p$ | $r$ | $q$ |
| (c) | $p, q$ | $s$ | $r, t$ | $q$ |
| (d) | $q, r$ | $q, p$ | $s$ | $s, t$ |
## Column-II
(p) 0
(q) $\frac{E}{R}$
(r) $\frac{E}{2 R}$
(s) $\quad I_{1}$ at $t=\infty$
(t) $\quad I_{2}$ at $t=0$
## Integer/ Numeric Questions
DIRECTIONS (Qs. 52-55): Following are integer based/ Numeric based questions. Each question, when worked out will result in one integer or numeric value.
52. A $100 \mu \mathrm{~F}$ capacitor in series with a $40 \Omega$ resistance is connected to a $110 \mathrm{~V}, 60 \mathrm{~Hz}$ supply.
(a) What is the maximum current in the circuit?
(b) What is the time lag between maximum current and maximum voltage?
53. A 50 volt a.c. applied across an RC (series) network. The rms voltage across the resistance is 40 volt, then find the potential across the capacitance.
54. An alternating emf $e=220 \sqrt{2} \sin 100 t \mathrm{~V}$ is applied to a capacitor $1 \mu \mathrm{~F}$. Find the current flowing through the capacitor.
55. A small town with a demand of 800 kW of electric power at 220 V is situated 15 km away from an electric power plant generating power at 440 V . The resistance of the two wire line carrying power is $0.5 \Omega$ per km . The town gets from the line through a $4000-220 \mathrm{~V}$ step down transformer at a sub-station in the town.
(a) Estimate the line power loss in the form of heat.
(b) How much power must be plant supply, assuming there is a negligible power loss due to leakage?
## SOLUTIONS (Brief Explanations of Selected Questions)
## Exercise Foundation Builder +
1. (a)
2. (c)
3. (a)
4. (b)
5. (c)
6. (c)
7. (b)
8. (b)
9. (d)
10. (b)
11. (b)
12. (b)
13. (b)
14. (c)
15. (b)
16. (a)
17. (c)
18. (d)
19. (b)
20. (b)
21. (c)
22. (b)
23. (c)
24. (b) $\mathrm{I}(0)=\frac{15 \times 100}{0.15 \times 10^{3}}=0.1 \mathrm{~A}$
$\mathrm{I}(\infty)=0$
$I(t)=[I(0)-I(\infty)] e^{\frac{-t}{L / R}}+i(\infty)$
$\mathrm{I}(\mathrm{t})=0.1 \mathrm{e}^{\frac{-\mathrm{t}}{\mathrm{L} / \mathrm{R}}}=0.1 \mathrm{e}^{\frac{\mathrm{R}}{\mathrm{L}}}$
$\mathrm{I}(\mathrm{t})=0.1 \mathrm{e}^{\frac{0.15 \times 1000}{0.03}}=0.67 \mathrm{~mA}$
25. (d)
Phasor diagram
For pure resistor circuit, power
$$
\mathrm{P}=\frac{\mathrm{V}^{2}}{\mathrm{R}} \Rightarrow \mathrm{~V}^{2}=\mathrm{PR}
$$
For L-R series circuit, power
$$
\mathrm{P}^{1}=\frac{\mathrm{V}^{2}}{\mathrm{Z}} \cos \theta=\frac{\mathrm{V}^{2}}{\mathrm{Z}} \cdot \frac{\mathrm{R}}{\mathrm{Z}}=\frac{\mathrm{PR}}{\mathrm{Z}^{2}} \cdot \mathrm{R}=\mathrm{P}\left(\frac{\mathrm{R}}{\mathrm{Z}}\right)^{2}
$$
26. (c) Voltage across secondary is zero. As primary voltage is constant, there is no change of magnetic flux of secondary coil and so no induction in secondary coil.
27. (b) Here
$$
\begin{aligned}
& i=\frac{e}{\sqrt{R^{2}+X_{L}^{2}}}=\frac{e}{\sqrt{R^{2}+\omega^{2} L^{2}}}=\frac{e}{\sqrt{R^{2}+4 \pi^{2} v^{2} L^{2}}} \\
& 10=\frac{220}{\sqrt{64+4 \pi^{2}(50)^{2} L}}\left[\because R=\frac{V}{I}=\frac{80}{10}=8\right]
\end{aligned}
$$
On solving we get
$$
\mathrm{L}=0.065 \mathrm{H}
$$
28. (b) As we know, power $\mathrm{P}=\mathrm{V}_{\mathrm{rms}} \cdot \mathrm{I}_{\mathrm{rms}} \cos \phi$ as $\cos \phi=0 \quad\left(\because \phi=90^{\circ}\right)$
$\therefore \quad$ Power consumed $=0$ (in one complete cycle)
29. (a) Given: $\mathrm{L}=20 \mathrm{mH} ; \mathrm{C}=50 \mu \mathrm{~F} ; \mathrm{R}=40 \Omega$
$\mathrm{V}=10 \sin 340 \mathrm{t}$
$\therefore \quad \mathrm{V}_{\text {runs }}=\frac{10}{\sqrt{2}}$
$\mathrm{X}_{\mathrm{C}}=\frac{1}{\omega \mathrm{C}}=\frac{1}{340 \times 50 \times 10^{-6}}=58.8 \Omega$
$\mathrm{X}_{\mathrm{L}}=\omega \mathrm{L}=340 \times 20 \times 10^{-3}=6.8 \Omega$
Impedance, $\mathrm{Z}=\sqrt{\mathrm{R}^{2}+\left(\mathrm{X}_{\mathrm{C}}-\mathrm{X}_{\mathrm{L}}\right)^{2}}$
$=\sqrt{40^{2}+(58.8-6.8)^{2}}=\sqrt{4304} \Omega$
Power loss in A.C. circuit,
$\mathrm{P}=\mathrm{i}_{\text {rms }}^{2} \mathrm{R}=\left(\frac{\mathrm{V}_{\text {rms }}}{\mathrm{Z}}\right)^{2} \mathrm{R}$
$=\left(\frac{10 / \sqrt{2}}{\sqrt{4304}}\right)^{2} \times 40=\frac{50 \times 40}{4304} \simeq 0.51 \mathrm{~W}$
30. (a) Power dissipated in an LCR series circuit connected to an a.c. source of emf E
$$
\begin{aligned}
\mathrm{P} & =\mathrm{E}_{\mathrm{rms}} \mathrm{i}_{\mathrm{rms}} \cos \phi=\frac{E_{r m s}^{2} R}{Z^{2}}=\frac{E_{r m s}^{2} R}{R^{2}+\left(\omega L-\frac{1}{C \omega}\right)^{2}} \\
& =\frac{\left(\frac{10}{\sqrt{2}}\right)^{2} \times 50}{(50)^{2}+\left(314 \times 20 \times 10^{-3}-\frac{1}{314 \times 100 \times 10^{-6}}\right)^{2}}
\end{aligned}
$$
Solving we get, $\mathrm{P}=0.79 \mathrm{~W}$
31. (a) Quality factor,
$Q=\frac{1}{R} \sqrt{\frac{L}{C}}=\frac{1}{100} \sqrt{\frac{80 \times 10^{-3}}{2 \times 10^{-6}}}$
$=\frac{1}{100} \sqrt{40 \times 10^{3}}=\frac{200}{100}=2$
32. (b) Given :
Capacitance, $C=40 \mu \mathrm{~F}=40 \times 10^{-6} \mathrm{~F}$
Frequency, $f=50 \mathrm{~Hz}$
$\therefore \omega=2 \pi f=100 \pi$
$\varepsilon_{\text {rms }}=200 \mathrm{~V}$
$$
\begin{aligned}
\therefore I_{\mathrm{rms}} & =\frac{\varepsilon_{\mathrm{rms}}}{X_{C}}=\frac{\varepsilon_{\mathrm{rms}}}{\frac{1}{C \omega}} \\
& =200 \times 40 \times 10^{-6} \times 2 \pi \times 50=2.5 \mathrm{~A} .
\end{aligned}
$$
33. (a, d)
34. $(\mathrm{a}, \mathrm{b}, \mathrm{d})$
35. $(\mathrm{a}, \mathrm{b})$
36. (b, c, d)
37. (b,c,d)
38. $(b, c)$
39. (b)
40. (a)
41. (a)
42. (d)
43. (b)
44. (b)
45. (a)
46. (a)
47. (b)
48. (a)
49. (b)
50. (a)
51. (b)
52. (a) ( 3.24 A ) Here, $\mathrm{C}=100 \mu \mathrm{~F}=100 \times 10^{-6} \mathrm{~F}, \mathrm{R}=40 \Omega$, $\mathrm{V}_{\mathrm{rms}}=110 \mathrm{~V}, \mathrm{f}=60 \mathrm{~Hz}$
Peak voltage, $\mathrm{V}_{0}=\sqrt{2} \cdot \mathrm{~V}_{\text {rms }}=110 \sqrt{2}=155.54 \mathrm{~V}$
Circuit impedance,
$$
\begin{aligned}
Z= & \sqrt{R^{2}+\frac{1}{\omega^{2} C^{2}}}=\sqrt{40^{2}+\frac{1}{\left(2 \times \pi \times 60 \times 100 \times 10^{-6}\right)^{2}}} \\
& =\sqrt{1600+703.60}=\sqrt{2303.60}=48 \Omega
\end{aligned}
$$
Hence, maximum current in coil,
$$
\mathrm{I}_{0}=\frac{\mathrm{V}_{0}}{\mathrm{Z}}=\frac{155.54}{48}=3.24 \mathrm{~A}
$$
(b) ( 1.551 ms ) Phase lead angle (for current),
$$
\begin{aligned}
\theta & =\tan ^{-1} \frac{1}{\omega \mathrm{CR}} \\
& =\tan ^{-1} \frac{1}{2 \times 3.14 \times 60 \times 100 \times 10^{-6} \times 40} \\
& =\tan ^{-1} 0.66315=33^{\circ} 33^{\prime}\left(\operatorname{taken} 33.5^{\circ}\right)
\end{aligned}
$$
Time lead,
$$
\begin{aligned}
\mathrm{t} & =\frac{\theta}{\omega}=\frac{\theta}{2 \pi v}=\frac{33.5}{360 \times 60} \\
& =0.001551 \mathrm{sec}=1.551 \times 10^{-3} \mathrm{sec}
\end{aligned}
$$
Voltage will lag current by time 1.551 ms .
53. $(30 \mathrm{~V}) V_{R C}=\sqrt{V_{R}^{2}+V_{C}^{2}}$
$\therefore 50=\sqrt{40^{2}+V_{C}^{2}} \Rightarrow V_{C}=30 \mathrm{~V}$
54. ( $\left.22 \times 10^{-3} \mathrm{~A}\right)$ Compare $e=220 \sqrt{2} \sin 100 t$ with $e=e_{0} \sin \omega t$ we get $\mathrm{e}_{0}=220 \sqrt{2}, \omega=100$
$\therefore \mathrm{X}_{\mathrm{c}} e_{0}=\frac{1}{\omega C}=10^{4} \quad \therefore I_{r m s}=\frac{e_{r m s}}{X_{C}}=22 \times 10^{-3} \mathrm{~A}$
55. The diagram shows the network :
For sub-station,
$$
\begin{aligned}
& \mathrm{P}=800 \mathrm{~kW}=800 \times 10^{3} \text { watt } \\
& \mathrm{V}=220 \mathrm{~V}
\end{aligned}
$$
$$
I_{S}=\frac{P}{V}=\frac{800 \times 10^{3}}{220}=\frac{40}{11} \times 10^{3} \mathrm{~A} .
$$
Primary current ( $I_{p}$ ) in sub-station transformer will be given by $\quad 4000 \times \mathrm{I}_{\mathrm{P}}=220 \times \mathrm{I}_{\mathrm{S}}$
$$
\mathrm{I}_{\mathrm{P}}=\frac{220 \times 40 \times 10^{3}}{11 \times 4000}=200 \mathrm{~A}
$$
(a) $(600 \mathrm{~kW})$ Hence transmission line current $=200 \mathrm{~A}$
Transmission line resistance $=2 \times 15 \times 0.5=15 \Omega$
Transmission line power loss
$=\mathrm{I}^{2} \mathrm{R}=200 \times 200 \times 15=6 \times 10^{5}$ watt $=600 \mathrm{~kW}$.
(b) $(1400 \mathrm{~kW})$ Power to be supplied by plant $=$ power required at substation + loss of power of transmission $=800+600=1400 \mathrm{~kW}$.
Matter Waves (de-Broglie Waves)
Waves associated with moving particle and it propagates in the form of wave packets with group velocity.
de-Broglie wavelength
Potential barrier Potential difference developed across depletion region i.e., region either side of junction free from charge carriers. $\mathrm{V}_{\mathrm{B}}$ for silicon
$=0.7 \mathrm{~V}$ and for germanium $\mathrm{V}_{\mathrm{B}}=0.3 \mathrm{~V}$ Width of depletion region is of the order of $10^{-6} \mathrm{~m}$
$\infty$
Binding Energy
$\mathrm{E}_{\mathrm{b}}=\Delta \mathrm{mc}^{2}$
Binding energy per nucleon
$=\frac{\Delta m \times 931}{A} \frac{\mathrm{MeV}}{\text { Nucleon }}$
Half life $\mathrm{t}_{1 / 2}=\frac{0.693}{\lambda}$
Mean life $\tau=\frac{1}{\lambda}=\frac{\mathrm{T}_{1 / 2}}{0.693}$
## THE ATOM
Observations and experiments have concluded that atom is the basic constituent of each substance; which is neutral and stable. In Vedas, references are given about the basic constituent of the substances. It is called atom. After the Rutherford experiments, it has been accepted that positive nucleus is the centre of the atom and electrons are revolving around the nucleus in different orbits. In last hundred years, scientists have discovered the following facts regarding the atom. These are :
(i) The atom as a whole is neutral.
(ii) The atom is stable.
(iii) The size of the atom is order of $10^{-10} \mathrm{~m}$.
(iv) The atom emits discrete radiations etc.
## THOMSON'S ATOMIC MODEL
This model suggests an atom to be a tiny sphere of radius $\approx 10^{-10} \mathrm{~m}$, containing the positive charge. The atom is electrically neutral. It contains an equal negative charge in the form of electrons, which are embedded randomly in this sphere, like seeds in a watermelon.
This model failed to explain:
(i) Large scattering angle of $\alpha$-particle
Fig 8.1 Thomson's atomic model
(ii) Origin of spectral lines observed in the spectrum of hydrogen atom.