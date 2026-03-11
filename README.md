# BactoWise

Assess bacterial genome quality and annotate genes — one command, one config file.

```
Stage 1:  CheckM          → completeness & contamination check
Stage 2:  Prokka + Bakta  → gene annotation (run in parallel)
```

If the genome fails QC thresholds, BactoWise warns you and continues — the scientist makes the final call.

---

## Setup

### 1. Install a container runtime

Bakta runs inside a container. Use **Singularity/Apptainer** on HPC/SLURM clusters, or **Docker** on a local workstation.

**Singularity / Apptainer (HPC — recommended for SLURM):**
```bash
# Most HPC clusters already have it — just load the module:
module load singularity

# If not available, contact your sysadmin, or install Apptainer locally:
# https://apptainer.org/docs/admin/main/installation.html
```

**Docker (local workstation):**
```bash
# Mac/Windows: download Docker Desktop from https://docker.com
# Linux:
sudo apt install docker.io && sudo systemctl start docker
sudo usermod -aG docker $USER && newgrp docker
```

Set the runtime in `pipeline.yaml` to match what you have:
```yaml
- name: bakta
  runtime: singularity   # or: docker
```

### 2. Install BactoWise

```bash
conda build conda_recipe/ -c bioconda -c conda-forge
conda install --use-local bactowise -c bioconda -c conda-forge
```

> **WSL users:** If `conda build` fails, see the [User Guide](DOCS.md#installation).

> **Note — testing a fresh install:** If you want to verify the package in a clean environment (recommended when iterating on the code), wipe and reinstall rather than updating in-place:
> ```bash
> conda build conda_recipe/ -c bioconda -c conda-forge
>
> conda env remove -n bactowise_dev -y
> conda create -n bactowise_dev python=3.12 -y
> conda activate bactowise_dev
> conda install --use-local bactowise -c bioconda -c conda-forge
> ```

---

## Running

```bash
# Optional but recommended — catch config errors before a long run
bactowise validate -c pipeline.yaml

# Run the pipeline
bactowise run -f genome.fasta -c pipeline.yaml
```

On first run, BactoWise will automatically download the required databases (~4 GB) and pull the Bakta container image before starting. Results land in `./results/` with subdirectories for each tool.

> **Note:** Databases can also be downloaded ahead of time with `bactowise db download`.
> See the [User Guide](DOCS.md#databases) for individual database options and how to
> manage existing downloads.

**Skip a tool** (e.g. if QC has already been done):

```bash
bactowise run -f genome.fasta -c pipeline.yaml --skip checkm
```

---

## Further reading

- **[User Guide](DOCS.md#user-guide)** — database commands, QC output, flags, troubleshooting
- **[Developer Guide](DOCS.md#developer-guide)** — pipeline.yaml field reference, how to add a new tool
