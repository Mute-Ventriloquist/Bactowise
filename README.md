# BactoWise

Assess bacterial genome quality and annotate genes — one command, one config file.

```
Stage 1:  CheckM                        → completeness & contamination check (skippable)
Stage 2:  Prokka + Bakta + PGAP         → gene annotation (run in parallel)
Stage 3:  Consensus Engine              → merge annotations into a single source of truth
Stage 4:  AMRFinderPlus                 → AMR genes, virulence factors, point mutations        ↑ all run
          Phigaro                       → prophage region detection                             in parallel
          Platon                        → plasmid contig classification                         (skippable)
          MEFinder                      → transposons, IS elements, integrons
          EggNOG-mapper                 → GO terms, KEGG pathways, COG categories
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

> **Storage requirements:** The full pipeline downloads ~56 GB of databases
> on first run (~2 GB CheckM, ~2 GB Bakta, ~30 GB PGAP, ~1.6 GB Platon,
> ~20 GB EggNOG). During a run, PGAP requires up to ~100 GB of working space.
> Databases can be pre-downloaded with `bactowise db download` — see the
> [User Guide](DOCS.md#2-databases) for details. Large downloads (PGAP, EggNOG)
> support automatic resume if the connection drops.

Results land in `./results/` by default. Use `-o` to write to a different location:

```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" -o /scratch/my_run
```

**Skip the QC stage** (stage 1) or **all supplementary annotations** (stage 4):
```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_1
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_4
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_1 --skip stage_4
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

## Stage 4 — Supplementary Annotations

Stage 4 runs after the Consensus Engine and provides five independent analyses
in parallel. Skip the entire stage with `--skip stage_4`.

| Tool | What it does | Input | Database |
|---|---|---|---|
| **AMRFinderPlus** | AMR genes, virulence factors, point mutations | genome FASTA | auto-managed inside conda env |
| **Phigaro** | Prophage region detection | genome FASTA | `~/.bactowise/databases/phigaro/` (~1.5 GB) |
| **Platon** | Plasmid contig classification | genome FASTA | `~/.bactowise/databases/platon/` (~2.8 GB) |
| **MEFinder** | Transposons, IS elements, integrons | genome FASTA | bundled with pip package |
| **EggNOG-mapper** | GO terms, KEGG pathways, COG categories | consensus `GENE.faa` | `~/.bactowise/databases/eggnog/` (~20 GB) |

EggNOG-mapper is the only stage 4 tool that uses a stage 3 output — it annotates
every protein in the consensus FASTA to provide biological context for each
consensus gene.

---

## Further reading

- **[User Guide](DOCS.md#user-guide)** — databases, QC output, stage 4 tool details, flags, troubleshooting
- **[Developer Guide](DOCS.md#developer-guide)** — pipeline.yaml field reference, local modifications, how to add a new tool
