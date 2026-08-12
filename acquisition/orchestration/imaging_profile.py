# imaging_profile.py
# ------------------------------------------------------------
# Save, list, and apply named "imaging profile" snapshots, one per
# experiment - objective, DIC prism/polarizer, analyzer, light path,
# condenser, zoom, filter turrets, and D-LEDI illumination channels - on
# top of nis_sdk.NISSdk.
#
# One file per experiment (protocols/imaging_profile_<experiment_name>.json),
# matching this repo's existing one-file-per-protocol convention (see
# protocols/example_protocol.yaml, protocols/test_protocol_short.yaml) -
# deliberately NOT one shared JSON file keyed by experiment the way
# stage_positions.json holds every saved position, so each experiment's
# profile is self-contained and can be checked in / shared individually.
#
# Real hardware (SDK) only - there's no mock imaging-profile simulation
# the way stage position has MockNIS, since these settings don't have a
# meaningful offline-dev equivalent.
#
# Workflow this exists for: set an imaging profile up visually in NIS-
# Elements once per experiment (objective, filters, DIC, illumination -
# whatever that experiment needs), capture it here under the experiment's
# name, then reapply it later from a script instead of re-clicking
# through the UI each time you resume or repeat that experiment.
#
# Does NOT trigger image capture/acquisition itself - only sets the
# microscope up to match a saved profile. Real capture via any SDK path
# is confirmed unavailable until JOBS Editor is licensed on this install
# (see acquisition/planned/nis_jobs_capture.py) - applying a profile is
# the "get the scope into the right state" half of "load a profile and
# acquire", not the capture half.
#
# Not part of the MCP server / stage-motion safety work - see
# nis_sdk.NISSdk.get_optical_configuration/apply_optical_configuration
# for the underlying SDK calls and their caveats (property semantics like
# whether iDLED1_POS is an intensity percent aren't independently
# calibrated the way XY/Z/PFS units were - working distance IS confirmed
# in mm, see that method's docstring).
# ------------------------------------------------------------

import argparse
import json
import re
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "protocols"
PROFILE_FILENAME_PREFIX = "imaging_profile_"
PROFILE_FILENAME_SUFFIX = ".json"

# Experiment names are used directly to build a filename - restricting to
# this set keeps a typo (a stray "/" or "..") from writing outside
# profiles_dir instead of just failing with a clear error.
_VALID_EXPERIMENT_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _profile_path(experiment_name: str, profiles_dir: Path) -> Path:
    if not _VALID_EXPERIMENT_NAME.match(experiment_name):
        raise ValueError(
            f"Invalid experiment name '{experiment_name}' - only letters, "
            "digits, underscores, and hyphens are allowed (it's used "
            "directly as a filename)."
        )
    return profiles_dir / f"{PROFILE_FILENAME_PREFIX}{experiment_name}{PROFILE_FILENAME_SUFFIX}"


class ImagingProfileManager:
    """Save, list, and apply named imaging-profile snapshots, one file per
    experiment - protocols/imaging_profile_<experiment_name>.json.
    """

    def __init__(self, profiles_dir: Path = PROFILES_DIR):
        # Lazy - NISSdk() blocks on an actual hardware connection attempt,
        # which list_profiles()/delete() (pure file operations) shouldn't
        # require. Only save_current()/apply() (the property accessor
        # below, via self._nis) actually need it. The import itself is
        # deferred too (not just the instantiation) - acquisition.backends.
        # nis_sdk imports pythoncom/win32com at module level, which don't
        # exist off Windows, so importing it eagerly would break
        # list_profiles()/delete() on any non-Windows dev machine too.
        self._nis_instance = None
        self._profiles_dir = profiles_dir

    @property
    def _nis(self) -> "NISSdk":
        if self._nis_instance is None:
            from acquisition.backends.nis_sdk import NISSdk

            self._nis_instance = NISSdk()
        return self._nis_instance

    def save_current(self, experiment_name: str) -> dict:
        """Read the microscope's current optical/device configuration and
        save it to protocols/imaging_profile_<experiment_name>.json.
        Overwrites any existing file for that experiment.
        """
        profile = self._nis.get_optical_configuration()
        path = _profile_path(experiment_name, self._profiles_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(profile, f, indent=2, sort_keys=True)
        return profile

    def list_profiles(self) -> list[str]:
        """Return the experiment names of every saved profile, found by
        scanning protocols/ for imaging_profile_*.json files."""
        if not self._profiles_dir.exists():
            return []
        pattern = f"{PROFILE_FILENAME_PREFIX}*{PROFILE_FILENAME_SUFFIX}"
        names = [
            path.stem[len(PROFILE_FILENAME_PREFIX):]
            for path in self._profiles_dir.glob(pattern)
        ]
        return sorted(names)

    def apply(self, experiment_name: str) -> dict:
        """Apply the saved imaging profile for `experiment_name`.

        Raises FileNotFoundError if no profile has been saved for that
        experiment. Physically moves the objective turret/filter wheels/
        light path to match - see NISSdk.apply_optical_configuration's
        docstring for what this does and does not account for (e.g. it
        never touches Z).
        """
        path = _profile_path(experiment_name, self._profiles_dir)
        if not path.exists():
            raise FileNotFoundError(
                f"No saved imaging profile for experiment '{experiment_name}' "
                f"(expected {path}). Known experiments: {self.list_profiles()}"
            )
        with open(path, "r") as f:
            profile = json.load(f)
        return self._nis.apply_optical_configuration(profile)

    def delete(self, experiment_name: str) -> None:
        """Remove a saved profile file. Raises FileNotFoundError if it doesn't exist."""
        _profile_path(experiment_name, self._profiles_dir).unlink()


def _print_profile(profile: dict) -> None:
    for name, value in profile.items():
        print(f"  {name}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save, list, and apply per-experiment imaging profiles "
        "(objective, filters, DIC, illumination) via the Ti2 ActiveX SDK.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    save_parser = subparsers.add_parser(
        "save", help="Save the microscope's CURRENT live setup under an experiment name."
    )
    save_parser.add_argument("experiment_name")

    apply_parser = subparsers.add_parser(
        "apply", help="Apply a previously saved experiment's imaging profile to the microscope."
    )
    apply_parser.add_argument("experiment_name")

    subparsers.add_parser("list", help="List every saved experiment's imaging profile.")

    delete_parser = subparsers.add_parser("delete", help="Delete a saved experiment's imaging profile.")
    delete_parser.add_argument("experiment_name")

    args = parser.parse_args()
    manager = ImagingProfileManager()

    if args.command == "save":
        profile = manager.save_current(args.experiment_name)
        print(f"Saved as experiment '{args.experiment_name}':")
        _print_profile(profile)

    elif args.command == "apply":
        profile = manager.apply(args.experiment_name)
        print(f"Applied experiment '{args.experiment_name}':")
        _print_profile(profile)

    elif args.command == "list":
        names = manager.list_profiles()
        if not names:
            print(f"No saved imaging profiles yet in {PROFILES_DIR}")
        else:
            print("Saved imaging profiles:")
            for name in names:
                print(f"  {name}")

    elif args.command == "delete":
        manager.delete(args.experiment_name)
        print(f"Deleted experiment '{args.experiment_name}'.")


if __name__ == "__main__":
    main()
