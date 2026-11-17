# DFT and MLIP checks
Extract only criteria needed by the question; unknown is a valid result.

- System: elements, compositions, bulk/surface/defect, phases and temperature/pressure.
- Reference calculations: functional (PBE, SCAN/r2SCAN, hybrid), dispersion, spin, pseudopotentials, convergence. Different DFT references are not automatically comparable.
- Training: dataset/version, energy/force/stress/magnetic labels, sampling, train/test overlap and leakage, fine-tuning data.
- Model: architecture, equivariance, locality/cutoff, charge/spin/long-range treatment and supported chemistry.
- Validation: errors with units and aggregation, held-out systems versus random structures, phonons, barriers, phase stability, MD stability and extrapolation.
- Practical claims: hardware, system size, precision, speed comparison, code/model/data availability.

A method mentioned in Introduction or References is not evidence it generated training labels. Low force MAE alone does not establish reliable long-time MD or transferability. Distinguish universal pretrained models, domain models and fine-tuned variants. Identify reference-data accuracy versus surrogate-model accuracy.
