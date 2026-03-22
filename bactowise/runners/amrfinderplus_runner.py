from __future__ import annotations

import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console


# Full mapping of genus/genus+species strings to AMRFinderPlus --organism values.
# Derived from `amrfinder --list_organisms` and the AMRFinderPlus documentation.
# Keys are lowercase to allow case-insensitive matching.
#
# Notes:
#   - Species-level keys are checked before genus-level keys, so
#     "staphylococcus aureus" → Staphylococcus_aureus takes priority over
#     "staphylococcus" → (no match).
#   - Shigella is intentionally mapped to Escherichia — AMRFinderPlus uses
#     the same point mutation set for both (documented NCBI behaviour).
#   - Neisseria gonorrhoeae has a dedicated taxon; other Neisseria fall through
#     to the genus-level Neisseria entry.
_ORGANISM_MAP: dict[str, str] = {
    # Species-level (checked first)
    "acinetobacter baumannii":          "Acinetobacter_baumannii",
    "clostridioides difficile":         "Clostridioides_difficile",
    "clostridium difficile":            "Clostridioides_difficile",  # old name
    "enterococcus faecalis":            "Enterococcus_faecalis",
    "enterococcus faecium":             "Enterococcus_faecium",
    "neisseria gonorrhoeae":            "Neisseria_gonorrhoeae",
    "pseudomonas aeruginosa":           "Pseudomonas_aeruginosa",
    "staphylococcus aureus":            "Staphylococcus_aureus",
    "staphylococcus pseudintermedius":  "Staphylococcus_pseudintermedius",
    "streptococcus agalactiae":         "Streptococcus_agalactiae",
    "streptococcus pneumoniae":         "Streptococcus_pneumoniae",
    "streptococcus pyogenes":           "Streptococcus_pyogenes",
    "vibrio cholerae":                  "Vibrio_cholerae",
    # Genus-level fallbacks
    "campylobacter":                    "Campylobacter",
    "escherichia":                      "Escherichia",
    "shigella":                         "Escherichia",   # AMRFinderPlus treats Shigella as Escherichia
    "klebsiella":                       "Klebsiella",
    "neisseria":                        "Neisseria",
    "salmonella":                       "Salmonella",
}


class AMRFinderPlusRunner(CondaToolRunner):
    """
    Stage 4 — AMRFinderPlus: antimicrobial resistance gene and point mutation detection.

    AMRFinderPlus scans for acquired AMR genes, virulence factors, stress
    resistance genes, and — for supported taxa — known resistance-causing
    point mutations.

    Point mutation auto-detection
    ------------------------------
    BactoWise automatically maps the organism name passed via `-n`/`--organism`
    to an AMRFinderPlus taxon string and adds `--organism <taxon>` to the
    command when a match is found. No manual configuration is required for
    supported organisms.

    Supported taxa for point mutation screening:
        Acinetobacter_baumannii, Campylobacter, Clostridioides_difficile,
        Enterococcus_faecalis, Enterococcus_faecium, Escherichia (incl. Shigella),
        Klebsiella, Neisseria, Neisseria_gonorrhoeae, Pseudomonas_aeruginosa,
        Salmonella, Staphylococcus_aureus, Staphylococcus_pseudintermedius,
        Streptococcus_agalactiae, Streptococcus_pneumoniae, Streptococcus_pyogenes,
        Vibrio_cholerae

    The `organism` param in pipeline.yaml overrides auto-detection if you need
    to force a specific taxon (e.g. when the genus name is ambiguous).

    Input sources
    -------------
    Nucleotide FASTA  : the original genome FASTA passed to `bactowise run`

    Database
    --------
    Downloaded automatically via `amrfinder -u` during preflight if not present.
    Stored inside the amrfinderplus_env conda environment's data directory.

    Optional params (set in pipeline.yaml under params:)
    -------------------------------------------------------
    organism : str   Manual AMRFinderPlus taxon override. Use `amrfinder -l`
                     to list valid values. Overrides auto-detection from -n.
    plus     : bool  Include virulence, stress, and biocide resistance genes
                     (default: true — strongly recommended).
    threads  : int   Number of threads (falls back to global_threads).

    Output
    ------
    <output_dir>/amrfinderplus/
        amrfinderplus_results.tsv   tab-delimited AMR findings
        logs/amrfinderplus.log      full execution log

    Conda package : ncbi-amrfinderplus (binary: amrfinder)
    """

    CONDA_PACKAGE = "ncbi-amrfinderplus"

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking amrfinderplus (stage 4)")

        if self.config.conda_env:
            self._ensure_amrfinderplus_env()
        else:
            if not self._tool_installed("amrfinder"):
                raise RuntimeError(
                    "  ✗  'amrfinder' not found on PATH and no conda_env configured.\n"
                    "     Add a conda_env block for 'amrfinderplus' in pipeline.yaml."
                )

        self._ensure_database()

        # Show point mutation status at preflight so the user knows upfront
        amr_taxon, source = self._resolve_organism()
        if source == "autodetect":
            console.print(
                f"  [success]✓[/success]  Point mutation screening: "
                f"[bold]{amr_taxon}[/bold] (auto-detected from '-n {self.organism}')"
            )
        elif source == "pipeline.yaml":
            console.print(
                f"  [warning]⚠[/warning]  Point mutation screening: [bold]{amr_taxon}[/bold] "
                f"(pipeline.yaml fallback)\n"
                f"     No AMRFinderPlus taxon match found for '{self.organism}' — "
                f"using organism: {amr_taxon} from pipeline.yaml instead.\n"
                f"     If this is unintentional, remove the organism param from pipeline.yaml."
            )
        else:
            console.print(
                f"  [muted]~  Point mutation screening: not available for "
                f"'{self.organism or '(no organism specified)'}'\n"
                f"     (supported taxa: Escherichia, Salmonella, Staphylococcus_aureus, "
                f"Streptococcus_pneumoniae, and others — see amrfinder -l)[/muted]"
            )

        try:
            result = subprocess.run(
                self._conda_run_cmd(["--version"]),
                capture_output=True, text=True,
            )
            raw = result.stdout.strip() or result.stderr.strip()
            installed_version = raw.split()[-1] if raw else "unknown"
            self._check_version(installed_version)
        except Exception:
            console.print(
                f"  [warning]⚠[/warning]  Could not determine installed version of amrfinder."
            )

    def _ensure_amrfinderplus_env(self) -> None:
        env_config  = self.config.conda_env
        env_name    = env_config.name
        conda_root  = self._find_conda_root()
        binary_path = Path(conda_root) / "envs" / env_name / "bin" / "amrfinder"

        if binary_path.exists():
            console.print(
                f"  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] "
                f"already exists — skipping creation."
            )
            return

        console.print(f"\n  Conda env [bold]'{env_name}'[/bold] not found. Creating it now...")
        console.print(f"    Channels: {env_config.channels}")
        console.print(f"    This is a one-time step and may take a few minutes.\n")

        conda_bin = self._find_conda_binary()
        packages  = [self.CONDA_PACKAGE] + env_config.dependencies

        cmd = [conda_bin, "create", "-n", env_name, "-y", "--strict-channel-priority"]
        for channel in env_config.channels:
            cmd += ["-c", channel]
        cmd += packages

        console.print(f"  Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to create conda env '{env_name}'.\n"
                f"     Try running manually:\n"
                f"     {' '.join(cmd)}"
            )

        console.print(
            f"\n  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] "
            f"created successfully."
        )

    def _ensure_database(self) -> None:
        console.print("  Checking AMRFinderPlus database...")

        check = subprocess.run(
            self._conda_run_cmd(["--database_version"]),
            capture_output=True, text=True,
        )

        if check.returncode == 0:
            db_version = (check.stdout.strip() or check.stderr.strip()).split()[-1]
            console.print(
                f"  [success]✓[/success]  AMRFinderPlus database present "
                f"(version [bold]{db_version}[/bold])."
            )
            return

        console.print(
            "  AMRFinderPlus database not found. Downloading now "
            "(this is a one-time step)..."
        )

        result = subprocess.run(self._conda_run_cmd(["-u"]), text=True)

        if result.returncode != 0:
            raise RuntimeError(
                "  ✗  Failed to download AMRFinderPlus database.\n"
                "     Try manually:\n"
                "       conda run -n amrfinderplus_env amrfinder -u"
            )

        console.print("  [success]✓[/success]  AMRFinderPlus database downloaded.")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting AMR gene detection...")

        output_tsv = self.output_dir / "amrfinderplus_results.tsv"
        log_file   = self.log_dir / "amrfinderplus.log"
        amr_taxon, source  = self._resolve_organism()

        cmd = self._build_command(fasta, output_tsv, amr_taxon)

        self._cprint(f"[label]Nucleotide:[/label] [muted]{fasta}[/muted]")
        self._cprint(f"[label]Output:[/label]     [muted]{output_tsv}[/muted]")
        if source == "autodetect":
            self._cprint(
                f"[label]Point mutations:[/label] [success]enabled[/success] "
                f"(--organism [bold]{amr_taxon}[/bold], auto-detected)"
            )
        elif source == "pipeline.yaml":
            self._cprint(
                f"[label]Point mutations:[/label] [warning]enabled via pipeline.yaml fallback[/warning] "
                f"(--organism [bold]{amr_taxon}[/bold])\n"
                f"  [warning]⚠[/warning]  No match for '{self.organism}' — "
                f"using {amr_taxon} from pipeline.yaml"
            )
        else:
            self._cprint(
                f"[label]Point mutations:[/label] [muted]not available for this organism[/muted]"
            )
        self._cprint(f"[label]Command:[/label]    [muted]{' '.join(cmd)}[/muted]")
        self._cprint(f"[label]Logging to:[/label] [muted]{log_file}[/muted]")

        with open(log_file, "w") as log:
            result = subprocess.run(
                cmd, stdout=log, stderr=subprocess.STDOUT, text=True,
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"[amrfinderplus] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._report_summary(output_tsv)

        self._cprint(
            f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]"
        )
        console.print()
        return self.output_dir

    def _resolve_organism(self) -> tuple[str | None, str]:
        """
        Determine the AMRFinderPlus --organism value to use.

        Returns (taxon, source) where source is one of:
          "autodetect"  — matched from the -n/--organism CLI input
          "pipeline.yaml" — fell back to the organism param in pipeline.yaml
          "none"        — no match found anywhere

        Priority:
          1. Auto-detected from self.organism (the -n/--organism CLI input)
          2. Explicit `organism` param in pipeline.yaml — fallback if -n yields no match
          3. (None, "none") — no point mutation screening
        """
        detected = _detect_amrfinder_organism(self.organism)
        if detected:
            return detected, "autodetect"

        manual = self.config.params.get("organism")
        if manual:
            return str(manual), "pipeline.yaml"

        return None, "none"

    def _build_command(
        self,
        fasta: Path,
        output_tsv: Path,
        amr_taxon: str | None,
    ) -> list[str]:
        """
        Build the amrfinder command in nucleotide-only mode.

            amrfinder -n <fasta> -o <tsv> -t <threads> [--plus] [--organism <taxon>]
        """
        threads = self.config.params.get("threads", self.global_threads)
        plus    = self.config.params.get("plus", True)

        tool_args = [
            "-n", str(fasta.resolve()),
            "-o", str(output_tsv),
            "-t", str(threads),
        ]

        if plus:
            tool_args.append("--plus")

        if amr_taxon:
            tool_args += ["--organism", amr_taxon]

        return self._conda_run_cmd(tool_args)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _report_summary(self, output_tsv: Path) -> None:
        if not output_tsv.exists():
            return
        try:
            with open(output_tsv) as f:
                lines = [l for l in f if not l.startswith("Protein") and l.strip()]
            count = len(lines)
            if count > 0:
                point_mutations = [l for l in lines if "POINT" in l]
                msg = f"[success]{count} AMR finding(s)[/success]"
                if point_mutations:
                    msg += f" including [success]{len(point_mutations)} point mutation(s)[/success]"
                self._cprint(f"{msg} — written to [muted]{output_tsv.name}[/muted].")
            else:
                self._cprint("No AMR genes or mutations detected.")
        except Exception:
            pass

    def _conda_run_cmd(self, tool_args: list[str]) -> list[str]:
        if self.config.conda_env:
            conda_bin = self._find_conda_binary()
            return [
                conda_bin, "run",
                "--no-capture-output",
                "-n", self.config.conda_env.name,
                "amrfinder",
            ] + tool_args
        else:
            return ["amrfinder"] + tool_args


def _detect_amrfinder_organism(organism: str) -> str | None:
    """
    Map a free-form organism name (as passed via -n) to an AMRFinderPlus
    --organism taxon string.

    Strategy (in order):
      1. Hardcoded map — instant, handles special cases like Shigella→Escherichia
         which the NCBI taxonomy tree cannot resolve (Shigella is a separate
         genus in NCBI but AMRFinderPlus groups it with Escherichia).
      2. NCBI Entrez API fallback — handles strain names, subspecies, old names,
         and any organism not in the hardcoded map. Walks the full NCBI lineage
         for the organism and checks each node name against the supported set.
         Fails gracefully with no match if the network is unavailable.

    Case-insensitive throughout.
    """
    if not organism:
        return None

    # 1. Try hardcoded map (covers Shigella→Escherichia and common names)
    result = _lookup_hardcoded(organism)
    if result:
        return result

    # 2. Fall back to NCBI lineage walk
    return _lookup_via_ncbi_lineage(organism)


def _lookup_hardcoded(organism: str) -> str | None:
    """Check the hardcoded map at genus+species level, then genus level."""
    parts = organism.strip().lower().split()
    if not parts:
        return None
    if len(parts) >= 2:
        genus_species = f"{parts[0]} {parts[1]}"
        if genus_species in _ORGANISM_MAP:
            return _ORGANISM_MAP[genus_species]
    return _ORGANISM_MAP.get(parts[0])


def _lookup_via_ncbi_lineage(organism: str) -> str | None:
    """
    Query the NCBI Entrez API to get the full taxonomic lineage for an organism
    name, then walk up the lineage checking each node name against the
    AMRFinderPlus supported set.

    This handles:
    - Strain names: "Staphylococcus aureus MRSA252" → lineage contains
      "Staphylococcus aureus" → Staphylococcus_aureus
    - Subspecies: "Campylobacter jejuni subsp. jejuni" → contains "Campylobacter"
    - Synonym/old names resolved by NCBI taxonomy

    Returns None on any network error or if no match is found in the lineage.
    """
    import json as _json

    _EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    _TIMEOUT = 8  # seconds — fast enough to not slow down preflight

    try:
        # Step 1: resolve name → taxid
        search_term = organism.strip().replace(" ", "+")
        search_url   = (
            f"{_EUTILS}/esearch.fcgi"
            f"?db=taxonomy&term={search_term}&retmode=json&retmax=1"
        )
        with urllib.request.urlopen(search_url, timeout=_TIMEOUT) as resp:
            data   = _json.loads(resp.read())
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return None
        taxid = ids[0]

        # Step 2: fetch lineage for the taxid
        fetch_url = (
            f"{_EUTILS}/efetch.fcgi"
            f"?db=taxonomy&id={taxid}&retmode=json"
        )
        with urllib.request.urlopen(fetch_url, timeout=_TIMEOUT) as resp:
            data = _json.loads(resp.read())

        # The lineage is a list of dicts: [{TaxId, ScientificName, Rank}, ...]
        # plus the organism itself. Walk from species up to root.
        result_set = data.get("result", {})
        tax_record = result_set.get(taxid, {})

        lineage_nodes = tax_record.get("lineage", [])
        # Add the organism itself (its own genus/species names are in the record)
        sci_name = tax_record.get("scientificname", "")
        lineage_names = [n.get("scientificname", "") for n in reversed(lineage_nodes)]
        lineage_names.insert(0, sci_name)

        # Walk from most specific to least specific, checking each name
        for name in lineage_names:
            # Try "genus species" exact match first, then genus-only
            result = _lookup_hardcoded(name)
            if result:
                return result

    except Exception:
        # Network unavailable, timeout, unexpected response format — fail silently
        pass

    return None

