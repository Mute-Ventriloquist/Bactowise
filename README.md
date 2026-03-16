# BactoWise

Assess bacterial genome quality and annotate genes — one command, one config file.

```
Stage 1:  CheckM                    → completeness & contamination check
Stage 2:  Prokka + Bakta + PGAP*    → gene annotation (run in parallel)

* PGAP is optional — see setup below.
```

If the genome fails QC thresholds, BactoWise warns you and continues — the scientist makes the final call.

---

## Setup

### 1. Install Singularity or Apptainer

Bakta and PGAP run inside Singularity containers. Apptainer is the actively
maintained community fork and is recommended for new installs. The two are
fully interchangeable — BactoWise detects whichever is available on your PATH.

**On an HPC cluster:**
```bash
module load singularity
# or: module load apptainer
```

**On a local workstation (WSL2, Linux):**
```bash
sudo add-apt-repository -y ppa:apptainer/ppa
sudo apt update
sudo apt install -y apptainer
```

Verify it works:
```bash
apptainer exec docker://alpine cat /etc/alpine-release
```

### 2. Install BactoWise

```bash
conda build conda_recipe/ -c bioconda -c conda-forge
conda install --use-local bactowise -c bioconda -c conda-forge
```

> **WSL users:** If `conda build` fails, see the [User Guide](DOCS.md#1-installation).

> **Note — testing a fresh install:** To verify the package in a clean
> environment (recommended when iterating on the code), wipe and reinstall
> rather than updating in-place:
> ```bash
> conda build conda_recipe/ -c bioconda -c conda-forge
>
> conda env remove -n bactowise_dev -y
> conda create -n bactowise_dev python=3.12 -y
> conda activate bactowise_dev
> conda install --use-local bactowise -c bioconda -c conda-forge
> ```

### 3. Download databases

**Core databases (~4 GB, required):**
```bash
bactowise db download
```
Downloads CheckM (~2 GB) and Bakta (~2 GB). The Bakta Singularity image
(~500 MB) is pulled automatically on first run.

**PGAP supplemental data (~30 GB, optional):**
```bash
bactowise db download --pgap
```
Only needed if you want to run PGAP annotation. This is a large one-time
download — plan accordingly. See the [User Guide](DOCS.md#2-databases) for details.

---

## Running

```bash
bactowise run -f genome.fasta
```

Results land in `./results/` with subdirectories for each tool.

**Skip a tool** (e.g. if QC has already been done):
```bash
bactowise run -f genome.fasta --skip checkm
```

**Bypass annotation with pre-computed GFF files:**
```bash
# With 3 annotation tools active (prokka + bakta + pgap):
bactowise run -f genome.fasta \
  --gff bakta:/path/to/bakta.gff3 \
  --gff prokka:/path/to/prokka.gff \
  --gff pgap:/path/to/pgap.gff

# With 2 annotation tools (prokka + bakta only):
bactowise run -f genome.fasta \
  --gff bakta:/path/to/bakta.gff3 \
  --gff prokka:/path/to/prokka.gff
```

---

## Further reading

- **[User Guide](DOCS.md#user-guide)** — database commands, QC output, flags, troubleshooting
- **[Developer Guide](DOCS.md#developer-guide)** — pipeline.yaml field reference, local modifications, how to add a new tool
