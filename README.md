# BactoWise

Assess bacterial genome quality and annotate genes — one command, one config file.

```
Stage 1:  CheckM                 → completeness & contamination check
Stage 2:  Prokka + Bakta + PGAP  → gene annotation (run in parallel)
Stage 3:  Consensus Engine       → merge annotations into a single source of truth
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

---

## Running

```bash
bactowise run -f genome.fasta -n "Genus species"
```

The `-n` flag is the organism name as a valid NCBI Taxonomy string
(e.g. `"Mycoplasmoides genitalium"`, `"Escherichia coli"`). It is passed to
PGAP (required), and also improves labelling in Prokka and Bakta.

On first run, BactoWise automatically sets up everything it needs — conda
environments, container images, and all required databases. Just run it.

> **Storage and compute requirements:** The full pipeline requires downloading
> approximately ~34 GB of database files on first run (~2 GB CheckM, ~2 GB
> Bakta, ~30 GB PGAP). During a run, PGAP requires up to ~100 GB of working
> space. Databases can also be downloaded ahead of time with
> `bactowise db download` and `bactowise db download --pgap` — see the
> [User Guide](DOCS.md#2-databases) for details.

Results land in `./results/` by default. Use `-o` to write to a different location:

```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" -o /scratch/my_run
```

**Skip the QC stage** (stage 1 is the only skippable stage):
```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_1
```

**Bypass annotation with pre-computed GFF files:**

Provide a GFF for any subset of annotation tools — the rest run normally:
```bash
# Bypass all three
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" \
  --gff bakta:/path/to/bakta.gff3 \
  --gff prokka:/path/to/prokka.gff \
  --gff pgap:/path/to/pgap.gff

# Bypass only Prokka — Bakta and PGAP still run
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" \
  --gff prokka:/path/to/prokka.gff
```

---

## Further reading

- **[User Guide](DOCS.md#user-guide)** — database commands, QC output, flags, troubleshooting
- **[Developer Guide](DOCS.md#developer-guide)** — pipeline.yaml field reference, local modifications, how to add a new tool
