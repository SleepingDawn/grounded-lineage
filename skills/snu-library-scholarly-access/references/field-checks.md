# Field checks: what makes two results comparable

Every engineering field has a few facts that decide whether two papers' numbers can be set side by side. Write them down once per review, before screening, as 5–8 short lines, and extract only those the question needs; "not stated" is a valid finding. Take them from the field itself, not from memory:

1. The field's test standards and reporting conventions, where they exist (ASTM/ISO test methods for materials and structures, IEEE/IEC conventions for devices and power systems, ASME V&V 10/20 for simulation verification and validation, dataset and benchmark cards for machine learning).
2. The methods and limitations sections of two recent reviews: what they say makes studies disagree.
3. The comparisons the reviews refuse to make, and why.

Cover these six questions, in the field's own terms:

| Question | Examples from different engineering fields |
|---|---|
| **What was studied?** The material, specimen, device or system and its conditions | alloy, heat treatment, specimen geometry; cell chemistry, temperature, C-rate; structure, load case, boundary conditions; dataset and task |
| **Against what reference?** Ground truth, baseline or reference level | standard test result; reference calculation or higher-fidelity simulation; baseline design or controller; state-of-the-art model on the same split |
| **From which data?** Provenance, calibration, overlap between training and test | measurement setup and calibration; dataset version and train/test leakage; number of specimens or runs |
| **With which method?** The choice that drives the result | approximation level or interatomic model; mesh, solver, turbulence model; fabrication route; architecture and training budget |
| **How was it validated?** What the claim was tested on | repeated specimens and scatter; held-out conditions or systems; mesh/time-step convergence; field or in-service data |
| **What is claimed in practice?** Cost, scale, availability | efficiency, power density, lifetime; runtime and hardware; manufacturability, cost per unit; code, data and model availability |

Typical traps: a method named in the introduction or references is not the method that produced the result; one headline metric (an average error, a peak efficiency, a best-case cycle life) does not establish the broader claim; results on different references, test conditions or definitions are not comparable without saying so.

Keep the checklist in the review's method section so the reader sees what was checked. A field that already has a checklist here (for example [dft-mlip.md](dft-mlip.md)) starts from it.
