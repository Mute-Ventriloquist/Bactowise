# BactoWise

Assess bacterial genome quality and annotate genes — one command, one config file.

```
Stage 1:  CheckM          → completeness & contamination check
Stage 2:  Prokka + Bakta  → gene annotation (run in parallel)
```

If the genome fails QC thresholds, BactoWise warns you and continues — the scientist makes the final call.

---

## Setup

### 1. Install Docker

Bakta runs inside Docker. Install Docker Desktop for [Mac/Windows](https://docker.com) or on Linux:

```bash
sudo apt install docker.io && sudo systemctl start docker
sudo usermod -aG docker $USER && newgrp docker
```

### 2. Install BactoWise

```bash
conda build conda_recipe/ -c bioconda -c conda-forge
conda install --use-local bactowise -c bioconda -c conda-forge
```

> **WSL users:** If `conda build` fails, see the [User Guide](DOCS.md#installation).

### 3. Download databases (~4 GB, one-time)

```bash
bactowise db download
```

This fetches the CheckM and Bakta databases and stores them under `~/.bactowise/databases/`.
The default `pipeline.yaml` already points to these paths.

> Databases can also be downloaded automatically on first run — see the [User Guide](DOCS.md#databases).

---

## Running

```bash
# Optional but recommended — catch config errors before a long run
bactowise validate -c pipeline.yaml

# Run the pipeline
bactowise run -f genome.fasta -c pipeline.yaml
```

Results land in `./results/` with subdirectories for each tool.

**Skip a tool** (e.g. if QC has already been done):

```bash
bactowise run -f genome.fasta -c pipeline.yaml --skip checkm
```

---

## Further reading

- **[User Guide](DOCS.md#user-guide)** — database commands, QC output, flags, troubleshooting
- **[Developer Guide](DOCS.md#developer-guide)** — pipeline.yaml field reference, how to add a new tool
