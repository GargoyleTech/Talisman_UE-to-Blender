"""Game-neutral, Blender-independent Sequencer graph, timing and curve readers."""

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
import math


def value(item, default=0):
    while isinstance(item, dict) and "Value" in item:
        item = item["Value"]
    return default if item is None else item


def number(item, default=0.0):
    try:
        result = float(value(item, default))
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def guid(item):
    result = str(item or "").replace("-", "").upper()
    return "" if not result.strip("0") else result


def asset_path(item):
    path = item.get("ObjectPath", "") if isinstance(item, dict) else str(item or "")
    if "'" in path:
        path = path.split("'", 1)[1].rstrip("'")
    path = path.replace("\\", "/").split(":", 1)[0]
    if "." in path.rsplit("/", 1)[-1]:
        path = path.rsplit(".", 1)[0]
    return path


def rate(item, default):
    if not item:
        return Fraction(default)
    numerator = number(item.get("Numerator"), default)
    denominator = number(item.get("Denominator"), 1)
    if numerator <= 0 or denominator <= 0:
        raise ValueError("Invalid Sequencer rational frame rate.")
    return Fraction(str(numerator)) / Fraction(str(denominator))


def bounds(properties, fallback):
    raw = value(properties.get("SectionRange", properties.get("PlaybackRange")), {})
    if not isinstance(raw, dict):
        return fallback
    result = []
    for index, key in enumerate(("LowerBound", "UpperBound")):
        bound = raw.get(key) or {}
        kind = str(bound.get("Type", "Open"))
        if "Open" in kind:
            result.append(fallback[index])
        else:
            tick = number(bound.get("Value"), fallback[index])
            # TRange<FFrameNumber> is discrete. Old seconds ranges are handled
            # separately, and are not rounded to integer frame boundaries.
            if index == 0 and "Exclusive" in kind:
                tick += 1
            elif index == 1 and "Inclusive" in kind:
                tick += 1
            result.append(tick)
    return tuple(result)


class Channel:
    def __init__(self, data=None, default=0):
        self.data = data or {}
        self.default = self.data.get("DefaultValue", default) if self.data.get("bHasDefaultValue", "DefaultValue" in self.data) else default
        if "Keys" in self.data:
            records = [(number(key.get("Time")), key) for key in self.data["Keys"]]
        else:
            records = [(number(tick), key) for tick, key in zip(self.data.get("Times") or [], self.data.get("Values") or [])]
        # Keep the last key at a duplicate time, just as an evaluated channel.
        self.keys = dict(sorted(records, key=lambda item: item[0]))
        self.times = list(self.keys)
        self.weighted = any(isinstance(key, dict) and
            str((key.get("Tangent") or {}).get("TangentWeightMode", "RCTWM_WeightedNone")) not in ("0", "RCTWM_WeightedNone", "None")
            for key in self.keys.values())

    def sample(self, tick):
        if not self.times:
            return number(self.default)
        index = bisect_right(self.times, tick)
        if index == 0:
            return number(self.keys[self.times[0]])
        if index >= len(self.times):
            return number(self.keys[self.times[-1]])
        left, right = self.times[index - 1:index + 1]
        a, b = self.keys[left], self.keys[right]
        mode = str(a.get("InterpMode", "RCIM_Linear")) if isinstance(a, dict) else "RCIM_Constant"
        if "Constant" in mode or mode == "0":
            return number(a)
        fraction = (tick - left) / (right - left)
        if "Cubic" not in mode and mode != "2":
            return number(a) * (1 - fraction) + number(b) * fraction
        ta = a.get("Tangent") or a
        tb = (b.get("Tangent") or b) if isinstance(b, dict) else {}
        f2, f3 = fraction ** 2, fraction ** 3
        return ((2*f3 - 3*f2 + 1) * number(a) + (f3 - 2*f2 + fraction) * number(ta.get("LeaveTangent")) * (right-left)
                + (-2*f3 + 3*f2) * number(b) + (f3-f2) * number(tb.get("ArriveTangent")) * (right-left))


class Sequence:
    def __init__(self, path, payload):
        self.path = path
        self.exports = payload.get("exports") or []
        self.identities = {item.get("ObjectPath"): item for item in self.exports if item.get("ObjectPath")}
        self.warnings = payload.get("warnings") or []
        root = next((item for item in self.exports if item.get("Type") == "LevelSequence"), None)
        if root is None:
            raise ValueError(f"Not a stock LevelSequence: {path}")
        self.root = root
        self.package_path = root.get("Package") or asset_path(path)
        self.movie = self.resolve(root.get("Properties", {}).get("MovieScene")) or next(
            (item for item in self.exports if item.get("Type") == "MovieScene"), None)
        if self.movie is None:
            raise ValueError(f"No MovieScene in {path}")
        properties = self.movie.get("Properties") or {}
        self.tick_rate = rate(properties.get("TickResolution"), 1)
        self.display_rate = rate(properties.get("DisplayRate"), 30)
        self.playback = bounds(properties, (0, 0))
        if self.playback[1] <= self.playback[0]:
            raise ValueError(f"No finite playback range in {path}")
        self.binding_refs = {}
        for entry in (root.get("Properties", {}).get("BindingReferences") or {}).get("BindingIdToReferences") or []:
            self.binding_refs[guid(entry.get("Key"))] = (entry.get("Value") or {}).get("References") or []
        self.bindings = {}
        for key in ("Spawnables", "Possessables"):
            for binding in properties.get(key) or []:
                self.bindings[guid(binding.get("Guid"))] = dict(binding, spawned=key == "Spawnables")
        self.tracks = {}
        for entry in properties.get("ObjectBindings") or []:
            binding_id = guid(entry.get("ObjectGuid"))
            self.bindings.setdefault(binding_id, {"Guid": binding_id, "Name": entry.get("BindingName") or binding_id, "spawned": False})
            self.tracks[binding_id] = [track for reference in entry.get("Tracks") or [] if (track := self.resolve(reference))]
        self.master_tracks = [track for reference in properties.get("MasterTracks") or [] if (track := self.resolve(reference))]
        camera = self.resolve(properties.get("CameraCutTrack"))
        if camera and camera not in self.master_tracks:
            self.master_tracks.append(camera)

    def resolve(self, reference):
        if not isinstance(reference, dict):
            return None
        path = reference.get("ObjectPath") or ""
        if path in self.identities:
            return self.identities[path]
        package, _, suffix = path.rpartition(".")
        # Numeric references are local only; don't resolve an external path
        # ending in a digit against this package's export list.
        own = self.package_path
        if suffix.isdigit() and asset_path(package).casefold() == asset_path(own).casefold():
            index = int(suffix)
            return self.exports[index] if 0 <= index < len(self.exports) else None
        return None

    def sections(self, track):
        properties = track.get("Properties") or {}
        if properties.get("bIsEvalDisabled"):
            return []
        result = []
        for key in ("Sections", "AnimationSections", "ConstraintSections"):
            for reference in properties.get(key) or []:
                section = self.resolve(reference)
                if section and section not in result and section.get("Properties", {}).get("bIsActive", True):
                    result.append(section)
        return result


@dataclass
class Instance:
    sequence: Sequence
    key: str
    scale: Fraction
    offset: Fraction
    clip: tuple
    parent: object = None

    def root_time(self, tick):
        return float(self.offset + self.scale * Fraction(str(tick)))

    def local_time(self, seconds):
        return float((Fraction(str(seconds)) - self.offset) / self.scale)

    def section_range(self, section):
        lower, upper = bounds(section.get("Properties") or {}, self.sequence.playback)
        return max(self.clip[0], self.root_time(lower)), min(self.clip[1], self.root_time(upper))

    def binding_key(self, binding_id):
        return self.key + ":" + guid(binding_id)


class Graph:
    def __init__(self, loader, path, *, max_instances=512):
        self.loader = loader
        self.cache = {}
        self.warnings = []
        self.instances = []
        self.max_instances = max_instances
        root = self.load(path)
        lower, upper = root.playback
        self.duration = float(Fraction(str(upper-lower)) / root.tick_rate)
        self._expand(Instance(root, "root", 1/root.tick_rate, -Fraction(str(lower))/root.tick_rate, (0, self.duration)), [])

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def load(self, path):
        key = asset_path(path).casefold()
        if key not in self.cache:
            self.cache[key] = Sequence(path, self.loader(path))
            for warning in self.cache[key].warnings:
                self.warn(f"{path}: {warning}")
        return self.cache[key]

    def _expand(self, instance, visiting):
        identity = asset_path(instance.sequence.package_path).casefold()
        if identity in visiting:
            self.warn(f"Cyclic subsequence skipped: {instance.sequence.path}")
            return
        if len(self.instances) >= self.max_instances:
            self.warn(f"Subsequence instance limit ({self.max_instances}) reached.")
            return
        self.instances.append(instance)
        sequence = instance.sequence
        for track_index, track in enumerate(sequence.master_tracks):
            if track.get("Type") not in {"MovieSceneCinematicShotTrack", "MovieSceneSubTrack"}:
                continue
            for index, section in enumerate(sequence.sections(track)):
                properties = section.get("Properties") or {}
                reference = properties.get("SubSequence")
                if not reference:
                    continue
                path = asset_path(reference)
                try:
                    child = self.load(path)
                    params = properties.get("Parameters") or {}
                    speed = number(params.get("TimeScale"), 1)
                    if speed <= 0:
                        self.warn(f"Nonpositive subsequence time scale skipped: {path}")
                        continue
                    section_lower, _ = bounds(properties, sequence.playback)
                    loop_start = child.playback[0] + number(params.get("StartFrameOffset"))
                    start_tick = loop_start + number(params.get("FirstLoopStartFrameOffset"))
                    end_tick = child.playback[1] - number(params.get("EndFrameOffset"))
                    if end_tick <= loop_start:
                        raise ValueError("Subsequence trims away its playback range.")
                    if params.get("bCanLoop"):
                        start_tick = loop_start + (start_tick-loop_start) % (end_tick-loop_start)
                    child_scale = instance.scale * sequence.tick_rate / child.tick_rate / Fraction(str(speed))
                    lower, upper = instance.section_range(section)
                    cursor = instance.root_time(section_lower)
                    loop = 0
                    while cursor < upper and loop < self.max_instances and len(self.instances) < self.max_instances:
                        offset = Fraction(str(cursor)) - Fraction(str(start_tick)) * child_scale
                        segment_end = float(offset + child_scale * Fraction(str(end_tick)))
                        if segment_end <= cursor:
                            break
                        clip = max(lower, cursor), min(upper, segment_end)
                        if clip[1] > clip[0]:
                            key = instance.key + "/" + str(track_index) + "." + str(index) + "." + str(loop)
                            self._expand(Instance(child, key, child_scale, offset, clip, instance), visiting + [identity])
                        if not params.get("bCanLoop"):
                            break
                        cursor, start_tick, loop = segment_end, loop_start, loop+1
                    if params.get("bCanLoop") and cursor < upper and (loop >= self.max_instances or len(self.instances) >= self.max_instances):
                        self.warn(f"Subsequence loop/instance limit ({self.max_instances}) reached: {path}")
                except Exception as exc:
                    self.warn(f"Subsequence unavailable ({path}): {exc}")

    def bindings(self):
        for instance in self.instances:
            for binding_id, binding in instance.sequence.bindings.items():
                yield instance, binding_id, binding
