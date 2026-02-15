import { useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";

const VOICES_PAGE_SIZE = 60;
const SOLUTIONS_PAGE_SIZE = 16;
const SOLUTION_MODAL_PAGE_SIZE = 24;

function bubbleRadius(value, max) {
  if (max <= 0) return 6;
  return Math.max(5, Math.min(36, 6 + (Math.sqrt(value) / Math.sqrt(max)) * 30));
}

function toLower(value) {
  return String(value || "").toLowerCase();
}

function normalizeToken(value) {
  return toLower(value).replace(/[^a-z0-9]+/g, "");
}

function toggleSelection(list, value) {
  if (list.includes(value)) return list.filter((item) => item !== value);
  return [...list, value];
}

function matchesSelected(selected, value) {
  if (!selected.length) return true;
  return selected.includes(value);
}

function pct(value, total) {
  if (!total) return "0%";
  return `${((value / total) * 100).toFixed(1)}%`;
}

function pctOrNA(value, total) {
  if (!total) return "n/a";
  return pct(value, total);
}

function formatTimestamp(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

function isArabicScriptMatch(query, voice) {
  if (!query.includes("arab")) return false;
  const script = toLower(voice.script);
  const writtenScript = toLower(voice.written_script);
  return script === "arab" || writtenScript.includes("arab");
}

function matchesAssistivePlatform(voice, selectedPlatform) {
  const target = toLower(selectedPlatform);
  if (!target || target === "all") return true;
  const voicePlatform = toLower(voice?.platform);
  const voicePlatformDisplay = toLower(voice?.platform_display);
  if (voicePlatform === target) return true;
  // Treat explicit cross-platform catalogs as available across app platforms.
  if (voicePlatform === "online" || voicePlatform === "local") return true;
  if (voicePlatformDisplay.includes("cross-platform")) return true;
  return false;
}

function previewItems(voice) {
  if (Array.isArray(voice.preview_audios) && voice.preview_audios.length) {
    return voice.preview_audios.filter((item) => item && item.url);
  }
  if (voice.preview_audio) {
    return [{ url: voice.preview_audio, language_code: null, source: "legacy" }];
  }
  return [];
}

function supportScore(level) {
  const token = toLower(level);
  if (token === "native") return 3;
  if (token === "compatible") return 2;
  if (token === "possible") return 1;
  return 0;
}

function supportParts(solution) {
  const items = [];
  if (solution.nativeCount) items.push(`Native ${solution.nativeCount.toLocaleString()}`);
  if (solution.compatibleCount) items.push(`Compatible ${solution.compatibleCount.toLocaleString()}`);
  if (solution.possibleCount) items.push(`Possible ${solution.possibleCount.toLocaleString()}`);
  return items.length ? items.join(" · ") : "No current matches";
}

function voiceOriginLabel(value) {
  const token = toLower(value);
  if (token === "all") return "Voice banking: any";
  if (token === "banked") return "Supports banked voices";
  if (token === "cloned") return "Supports cloned voices";
  if (token === "imported") return "Supports imported voices";
  if (token === "hybrid") return "Supports mixed voice sources";
  if (token === "builtin") return "Built-in voices";
  return value;
}

function humanizeToken(value) {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function Pagination({ page, pageCount, onPrev, onNext }) {
  if (pageCount <= 1) return null;
  return (
    <div className="pager">
      <button type="button" onClick={onPrev} disabled={page <= 1}>Previous</button>
      <span>Page {page} of {pageCount}</span>
      <button type="button" onClick={onNext} disabled={page >= pageCount}>Next</button>
    </div>
  );
}

function routeFromHash(hashValue) {
  const hash = String(hashValue || "").toLowerCase();
  if (hash.includes("/accessibility")) return "accessibility";
  return "voices";
}

function parseHashState(hashValue) {
  const raw = String(hashValue || "").replace(/^#/, "");
  const [pathPart, queryPart = ""] = raw.split("?");
  const route = routeFromHash(pathPart);
  const params = new URLSearchParams(queryPart);
  return {
    route,
    params: {
      lang: params.get("lang") || "",
      mode: params.get("mode") || "all",
      platform: params.get("platform") || "all",
      sub: params.get("sub") === "screenreader" ? "screenreader" : "aac",
    },
  };
}

function buildAccessibilityHash({ lang, mode, platform, sub }) {
  const params = new URLSearchParams();
  if (lang) params.set("lang", lang);
  if (mode && mode !== "all") params.set("mode", mode);
  if (platform && platform !== "all") params.set("platform", platform);
  if (sub === "screenreader") params.set("sub", "screenreader");
  const qs = params.toString();
  return `/accessibility${qs ? `?${qs}` : ""}`;
}

export default function App() {
  const initialHash = parseHashState(window.location.hash);
  const isNarrowViewport = typeof window !== "undefined" && window.matchMedia("(max-width: 900px)").matches;
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState(initialHash.route);

  const [query, setQuery] = useState("");
  const [selectedModes, setSelectedModes] = useState([]);
  const [selectedGenders, setSelectedGenders] = useState([]);
  const [selectedPlatforms, setSelectedPlatforms] = useState([]);
  const [selectedRuntimes, setSelectedRuntimes] = useState([]);
  const [selectedProviders, setSelectedProviders] = useState([]);
  const [selectedEngineFamilies, setSelectedEngineFamilies] = useState([]);
  const [selectedDistributionChannels, setSelectedDistributionChannels] = useState([]);
  const [excludedEngines, setExcludedEngines] = useState([]);
  const [showMap, setShowMap] = useState(true);
  const [voiceLayout, setVoiceLayout] = useState("grid");
  const [showVoiceFilters, setShowVoiceFilters] = useState(!isNarrowViewport);
  const [mapAutoCollapsed, setMapAutoCollapsed] = useState(false);
  const [assistiveSubtab, setAssistiveSubtab] = useState(initialHash.params.sub);
  const [solutionVoiceOrigin, setSolutionVoiceOrigin] = useState("all");
  const [accLanguageQuery, setAccLanguageQuery] = useState(initialHash.params.lang);
  const [accMode, setAccMode] = useState(initialHash.params.mode);
  const [accPlatform, setAccPlatform] = useState(initialHash.params.platform);
  const [showAssistiveFilters, setShowAssistiveFilters] = useState(!isNarrowViewport);
  const [voicePage, setVoicePage] = useState(1);
  const [solutionPage, setSolutionPage] = useState(1);
  const [selectedVoice, setSelectedVoice] = useState(null);
  const [selectedSolutionId, setSelectedSolutionId] = useState(null);
  const [solutionModalQuery, setSolutionModalQuery] = useState("");
  const [solutionModalPage, setSolutionModalPage] = useState(1);
  const mapWrapRef = useRef(null);

  useEffect(() => {
    const url = `${import.meta.env.BASE_URL}data/voices-site.json?v=${Date.now()}`;
    fetch(url, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setPayload(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    const onHashStateChange = () => {
      const state = parseHashState(window.location.hash);
      setView(state.route);
      if (state.route === "accessibility") {
        setAccLanguageQuery(state.params.lang);
        setAccMode(state.params.mode);
        setAccPlatform(state.params.platform);
        setAssistiveSubtab(state.params.sub);
      }
    };
    window.addEventListener("hashchange", onHashStateChange);
    if (!window.location.hash) {
      window.location.hash = "/voices";
    }
    return () => window.removeEventListener("hashchange", onHashStateChange);
  }, []);

  useEffect(() => {
    if (view !== "accessibility") return;
    const target = buildAccessibilityHash({
      lang: accLanguageQuery.trim(),
      mode: accMode,
      platform: accPlatform,
      sub: assistiveSubtab,
    });
    const current = String(window.location.hash || "").replace(/^#/, "");
    if (current === target) return;
    const nextUrl = `${window.location.pathname}${window.location.search}#${target}`;
    window.history.replaceState(null, "", nextUrl);
  }, [view, accLanguageQuery, accMode, accPlatform, assistiveSubtab]);

  useEffect(() => {
    if (view !== "voices" || !showMap || mapAutoCollapsed) return;
    const onScroll = () => {
      const el = mapWrapRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (rect.bottom < 64) {
        setShowMap(false);
        setMapAutoCollapsed(true);
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [view, showMap, mapAutoCollapsed]);

  const voices = payload?.voices || [];
  const summary = payload?.summary || {};
  const generatedAt = payload?.generated_at || "";
  const languageSpeakersTotal = Number(summary.language_speakers_total || 0);
  const languageSpeakersCovered = Number(summary.language_speakers_covered || 0);
  const languageSpeakersOnline = Number(summary.language_speakers_online_covered || 0);
  const languageSpeakersOffline = Number(summary.language_speakers_offline_covered || 0);
  const referenceLanguagesTotal = Number(summary.reference_languages_total || 0);
  const referenceLanguagesCovered = Number(summary.reference_languages_covered || 0);
  const referenceLanguagesOfflineCovered = Number(summary.reference_languages_offline_covered || 0);
  const referenceLanguagesNoTTS = Math.max(
    0,
    Number.isFinite(Number(summary.reference_languages_no_tts))
      ? Number(summary.reference_languages_no_tts)
      : referenceLanguagesTotal - referenceLanguagesCovered,
  );
  const referenceLanguagesNoOfflineTTS = Math.max(
    0,
    Number.isFinite(Number(summary.reference_languages_no_offline_tts))
      ? Number(summary.reference_languages_no_offline_tts)
      : referenceLanguagesTotal - referenceLanguagesOfflineCovered,
  );

  const platformOptions = useMemo(
    () => ["all", ...Object.keys(payload?.facets?.platforms || {}).sort((a, b) => a.localeCompare(b))],
    [payload],
  );
  const genderOptions = useMemo(
    () => ["all", ...Object.keys(payload?.facets?.genders || {}).sort((a, b) => a.localeCompare(b))],
    [payload],
  );
  const runtimeOptions = useMemo(
    () => ["all", ...Object.keys(payload?.facets?.runtimes || {}).sort((a, b) => a.localeCompare(b))],
    [payload],
  );
  const providerOptions = useMemo(
    () => ["all", ...Object.keys(payload?.facets?.providers || {}).sort((a, b) => a.localeCompare(b))],
    [payload],
  );
  const engineFamilyOptions = useMemo(
    () => ["all", ...Object.keys(payload?.facets?.engine_families || {}).sort((a, b) => a.localeCompare(b))],
    [payload],
  );
  const distributionChannelOptions = useMemo(
    () => ["all", ...Object.keys(payload?.facets?.distribution_channels || {}).sort((a, b) => a.localeCompare(b))],
    [payload],
  );
  const engineOptions = useMemo(
    () => Object.keys(payload?.facets?.engines || {}).sort((a, b) => a.localeCompare(b)),
    [payload],
  );
  const accessibilityHref = useMemo(() => {
    return `#${buildAccessibilityHash({
      lang: accLanguageQuery.trim(),
      mode: accMode,
      platform: accPlatform,
      sub: assistiveSubtab,
    })}`;
  }, [accLanguageQuery, accMode, accPlatform, assistiveSubtab]);

  const filteredVoices = useMemo(() => {
    const q = toLower(query).trim();
    return voices.filter((voice) => {
      if (!matchesSelected(selectedModes, voice.mode)) return false;
      if (!matchesSelected(selectedGenders, voice.gender)) return false;
      if (!matchesSelected(selectedPlatforms, voice.platform)) return false;
      if (!matchesSelected(selectedRuntimes, voice.runtime)) return false;
      if (!matchesSelected(selectedProviders, voice.provider)) return false;
      if (!matchesSelected(selectedEngineFamilies, voice.engine_family)) return false;
      if (!matchesSelected(selectedDistributionChannels, voice.distribution_channel)) return false;
      if (excludedEngines.includes(voice.engine)) return false;
      if (!q) return true;

      const haystack = [
        voice.id,
        voice.name,
        voice.country_code,
        voice.country_name,
        voice.language_name,
        voice.language_display,
        voice.runtime,
        voice.provider,
        voice.engine_family,
        voice.distribution_channel,
        voice.script,
        voice.written_script,
        ...(voice.language_codes || []),
      ].filter(Boolean).join(" ").toLowerCase();
      if (haystack.includes(q)) return true;
      return isArabicScriptMatch(q, voice);
    });
  }, [
    voices,
    query,
    selectedModes,
    selectedGenders,
    selectedPlatforms,
    selectedRuntimes,
    selectedProviders,
    selectedEngineFamilies,
    selectedDistributionChannels,
    excludedEngines,
  ]);

  useEffect(() => {
    setVoicePage(1);
  }, [
    query,
    selectedModes,
    selectedGenders,
    selectedPlatforms,
    selectedRuntimes,
    selectedProviders,
    selectedEngineFamilies,
    selectedDistributionChannels,
    excludedEngines,
  ]);

  const filteredStats = useMemo(() => {
    const online = filteredVoices.filter((v) => v.mode === "online").length;
    return { voices: filteredVoices.length, online, offline: filteredVoices.length - online };
  }, [filteredVoices]);
  const voiceActiveFilters = useMemo(() => {
    let total = 0;
    if (query.trim()) total += 1;
    if (selectedModes.length) total += 1;
    if (selectedGenders.length) total += 1;
    if (selectedPlatforms.length) total += 1;
    if (selectedRuntimes.length) total += 1;
    if (selectedProviders.length) total += 1;
    if (selectedEngineFamilies.length) total += 1;
    if (selectedDistributionChannels.length) total += 1;
    if (excludedEngines.length) total += 1;
    return total;
  }, [
    query,
    selectedModes,
    selectedGenders,
    selectedPlatforms,
    selectedRuntimes,
    selectedProviders,
    selectedEngineFamilies,
    selectedDistributionChannels,
    excludedEngines,
  ]);

  const mapPoints = useMemo(() => {
    const grouped = new Map();
    for (const voice of filteredVoices) {
      if (voice.latitude == null || voice.longitude == null) continue;
      const code = voice.country_code || "ZZ";
      if (!grouped.has(code)) {
        grouped.set(code, {
          country_code: code,
          country_name: voice.country_name || "Unknown",
          count: 0,
          online_count: 0,
          offline_count: 0,
          latitude_sum: 0,
          longitude_sum: 0,
          points: 0,
          languages: new Map(),
        });
      }
      const item = grouped.get(code);
      item.count += 1;
      if (voice.mode === "online") item.online_count += 1;
      else item.offline_count += 1;
      item.latitude_sum += Number(voice.latitude);
      item.longitude_sum += Number(voice.longitude);
      item.points += 1;
      const lang = voice.language_display || voice.language_name || voice.language_codes?.[0] || "Unknown";
      item.languages.set(lang, (item.languages.get(lang) || 0) + 1);
    }
    return Array.from(grouped.values())
      .filter((p) => p.points)
      .map((p) => ({
        ...p,
        latitude: p.latitude_sum / p.points,
        longitude: p.longitude_sum / p.points,
        top_languages: Array.from(p.languages.entries())
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5)
          .map(([name, count]) => ({ name, count })),
      }))
      .sort((a, b) => b.count - a.count);
  }, [filteredVoices]);

  const maxBubble = useMemo(() => mapPoints.reduce((max, p) => Math.max(max, p.count), 0), [mapPoints]);

  const accessibilityVoices = useMemo(() => {
    const q = toLower(accLanguageQuery).trim();
    return voices.filter((voice) => {
      if (accMode !== "all" && voice.mode !== accMode) return false;
      if (!matchesAssistivePlatform(voice, accPlatform)) return false;
      if (!q) return true;
      const haystack = [
        voice.language_name,
        voice.language_display,
        voice.script,
        voice.written_script,
        ...(voice.language_codes || []),
      ].filter(Boolean).join(" ").toLowerCase();
      if (haystack.includes(q)) return true;
      return isArabicScriptMatch(q, voice);
    });
  }, [voices, accLanguageQuery, accMode, accPlatform]);

  const solutionRows = useMemo(() => {
    const solutions = Array.isArray(payload?.solutions) ? payload.solutions : [];
    const runtimeSupport = Array.isArray(payload?.solution_runtime_support) ? payload.solution_runtime_support : [];
    const providerSupport = Array.isArray(payload?.solution_provider_support) ? payload.solution_provider_support : [];

    const runtimeBySolution = new Map();
    for (const row of runtimeSupport) {
      const solutionId = String(row.solution_id || "");
      if (!solutionId) continue;
      if (!runtimeBySolution.has(solutionId)) runtimeBySolution.set(solutionId, []);
      runtimeBySolution.get(solutionId).push({
        token: normalizeToken(row.runtime),
        score: supportScore(row.support_level),
        voiceOrigin: String(row.voice_origin || "").trim().toLowerCase(),
        requiresEnrollment: row.requires_enrollment === true,
        requiresUserAsset: row.requires_user_asset === true,
      });
    }

    const providerBySolution = new Map();
    for (const row of providerSupport) {
      const solutionId = String(row.solution_id || "");
      if (!solutionId) continue;
      if (!providerBySolution.has(solutionId)) providerBySolution.set(solutionId, []);
      providerBySolution.get(solutionId).push({
        token: normalizeToken(row.provider),
        score: supportScore(row.support_level),
        voiceOrigin: String(row.voice_origin || "").trim().toLowerCase(),
        requiresEnrollment: row.requires_enrollment === true,
        requiresUserAsset: row.requires_user_asset === true,
      });
    }

    const out = [];
    for (const solution of solutions) {
      if (!solution?.id) continue;
      if (assistiveSubtab === "aac" && toLower(solution.category) !== "aac") continue;
      if (assistiveSubtab === "screenreader" && toLower(solution.category) !== "screenreader") continue;
      if (accPlatform !== "all") {
        const platforms = Array.isArray(solution.platforms)
          ? solution.platforms.map((p) => String(p).toLowerCase())
          : [];
        if (!platforms.includes(accPlatform)) continue;
      }

      const runtimeRules = runtimeBySolution.get(solution.id) || [];
      const providerRules = providerBySolution.get(solution.id) || [];
      const voiceOrigins = new Set(
        [...runtimeRules, ...providerRules].map((r) => r.voiceOrigin).filter(Boolean),
      );
      if (solutionVoiceOrigin !== "all" && !voiceOrigins.has(solutionVoiceOrigin)) continue;

      const requiresEnrollment = [...runtimeRules, ...providerRules].some((r) => r.requiresEnrollment);
      const requiresUserAsset = [...runtimeRules, ...providerRules].some((r) => r.requiresUserAsset);
      let nativeCount = 0;
      let compatibleCount = 0;
      let possibleCount = 0;
      let total = 0;
      const matchedVoices = [];

      for (const voice of accessibilityVoices) {
        const runtimeToken = normalizeToken(voice.runtime);
        const providerToken = normalizeToken(voice.provider);
        let best = 0;
        let reason = "";
        for (const rule of runtimeRules) if (rule.token === runtimeToken) best = Math.max(best, rule.score);
        for (const rule of providerRules) if (rule.token === providerToken) best = Math.max(best, rule.score);
        const runtimeMatch = runtimeRules.some((rule) => rule.token === runtimeToken);
        const providerMatch = providerRules.some((rule) => rule.token === providerToken);
        if (runtimeMatch && providerMatch) reason = "runtime + provider";
        else if (runtimeMatch) reason = "runtime";
        else if (providerMatch) reason = "provider";
        if (!best) continue;
        total += 1;
        if (best >= 3) nativeCount += 1;
        else if (best >= 2) compatibleCount += 1;
        else possibleCount += 1;
        matchedVoices.push({
          voice,
          score: best,
          reason,
        });
      }

      out.push({
        ...solution,
        total,
        nativeCount,
        compatibleCount,
        possibleCount,
        voiceOrigins: Array.from(voiceOrigins).sort(),
        requiresEnrollment,
        requiresUserAsset,
        matchedVoices,
      });
    }
    return out.sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
  }, [
    payload,
    accessibilityVoices,
    assistiveSubtab,
    solutionVoiceOrigin,
    accPlatform,
  ]);

  useEffect(() => {
    setSolutionPage(1);
  }, [assistiveSubtab, solutionVoiceOrigin, accLanguageQuery, accMode, accPlatform, payload]);
  const assistiveActiveFilters = useMemo(() => {
    let total = 0;
    if (accLanguageQuery.trim()) total += 1;
    if (accMode !== "all") total += 1;
    if (accPlatform !== "all") total += 1;
    if (solutionVoiceOrigin !== "all") total += 1;
    return total;
  }, [accLanguageQuery, accMode, accPlatform, solutionVoiceOrigin]);

  const solutionVoiceOriginOptions = useMemo(() => {
    const runtimeSupport = Array.isArray(payload?.solution_runtime_support) ? payload.solution_runtime_support : [];
    const providerSupport = Array.isArray(payload?.solution_provider_support) ? payload.solution_provider_support : [];
    const origins = new Set();
    for (const row of [...runtimeSupport, ...providerSupport]) {
      const origin = String(row?.voice_origin || "").trim().toLowerCase();
      if (origin) origins.add(origin);
    }
    return ["all", ...Array.from(origins).sort((a, b) => a.localeCompare(b))];
  }, [payload]);

  const voicePageCount = Math.max(1, Math.ceil(filteredVoices.length / VOICES_PAGE_SIZE));
  const solutionPageCount = Math.max(1, Math.ceil(solutionRows.length / SOLUTIONS_PAGE_SIZE));
  const visibleVoices = filteredVoices.slice((voicePage - 1) * VOICES_PAGE_SIZE, voicePage * VOICES_PAGE_SIZE);
  const visibleSolutions = solutionRows.slice((solutionPage - 1) * SOLUTIONS_PAGE_SIZE, solutionPage * SOLUTIONS_PAGE_SIZE);
  const selectedSolution = useMemo(
    () => solutionRows.find((s) => s.id === selectedSolutionId) || null,
    [solutionRows, selectedSolutionId],
  );
  const selectedSolutionFilteredMatches = useMemo(() => {
    if (!selectedSolution) return [];
    const q = toLower(solutionModalQuery).trim();
    if (!q) return selectedSolution.matchedVoices || [];
    return (selectedSolution.matchedVoices || []).filter((item) => {
      const v = item.voice || {};
      const haystack = [
        v.id,
        v.name,
        v.engine,
        v.runtime,
        v.provider,
        v.language_name,
        v.language_display,
        ...(v.language_codes || []),
      ].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }, [selectedSolution, solutionModalQuery]);
  const solutionModalPageCount = Math.max(
    1,
    Math.ceil(selectedSolutionFilteredMatches.length / SOLUTION_MODAL_PAGE_SIZE),
  );
  const visibleSolutionModalMatches = useMemo(() => {
    return selectedSolutionFilteredMatches.slice(
      (solutionModalPage - 1) * SOLUTION_MODAL_PAGE_SIZE,
      solutionModalPage * SOLUTION_MODAL_PAGE_SIZE,
    );
  }, [selectedSolutionFilteredMatches, solutionModalPage]);

  useEffect(() => {
    setSolutionModalPage(1);
  }, [solutionModalQuery, selectedSolutionId]);

  const voiceBankingProviders = useMemo(() => {
    const providerRows = Array.isArray(payload?.solution_provider_support)
      ? payload.solution_provider_support
      : [];
    const allowedOrigins = new Set(solutionVoiceOrigin === "all" ? ["banked", "cloned", "hybrid", "imported"] : [solutionVoiceOrigin]);
    const visibleSolutionIds = new Set(solutionRows.map((s) => s.id));
    const byProvider = new Map();
    for (const row of providerRows) {
      const solutionId = String(row.solution_id || "");
      if (!visibleSolutionIds.has(solutionId)) continue;
      const origin = String(row.voice_origin || "").trim().toLowerCase();
      if (!allowedOrigins.has(origin)) continue;
      const providerName = String(row.provider || "").trim();
      if (!providerName) continue;
      if (!byProvider.has(providerName)) {
        byProvider.set(providerName, {
          provider: providerName,
          voiceOrigins: new Set(),
          apps: new Set(),
        });
      }
      const item = byProvider.get(providerName);
      item.voiceOrigins.add(origin);
      item.apps.add(solutionId);
    }
    return Array.from(byProvider.values())
      .map((item) => ({
        provider: item.provider,
        voiceOrigins: Array.from(item.voiceOrigins).sort(),
        appCount: item.apps.size,
        apps: Array.from(item.apps).sort(),
      }))
      .sort((a, b) => b.appCount - a.appCount || a.provider.localeCompare(b.provider));
  }, [payload, solutionRows, solutionVoiceOrigin]);

  if (loading) return <main className="app"><p className="status">Loading voices atlas...</p></main>;
  if (error) return <main className="app"><p className="status error">{error}</p></main>;

  return (
    <main className="app">
      <header className="hero">
        <p className="kicker">TTS Dataset</p>
        <h1>Global Voice Atlas</h1>
        <p className="lede">
          Explore voices by geography, voice id, language, country, mode, and taxonomy fields.
        </p>
        <p className="meta">
          Focus: consumer-ready, in-use TTS solutions rather than developer tooling or raw model catalogs.
          Dataset quality and coverage are actively being improved.
        </p>
        <p className="coverage-inline">
          Updated {formatTimestamp(generatedAt)}. Speaker coverage: online {pctOrNA(languageSpeakersOnline, languageSpeakersTotal)},
          offline {pctOrNA(languageSpeakersOffline, languageSpeakersTotal)}, total {pctOrNA(languageSpeakersCovered, languageSpeakersTotal)}.
          Languages with no TTS: {referenceLanguagesNoTTS}/{referenceLanguagesTotal} ({pctOrNA(referenceLanguagesNoTTS, referenceLanguagesTotal)}).
          Languages with no offline TTS: {referenceLanguagesNoOfflineTTS}/{referenceLanguagesTotal} ({pctOrNA(referenceLanguagesNoOfflineTTS, referenceLanguagesTotal)}).
        </p>
        <div className="view-switch">
          <a className={view === "voices" ? "active" : ""} href="#/voices">Voices</a>
          <a className={view === "accessibility" ? "active" : ""} href={accessibilityHref}>Assistive Technology</a>
        </div>
      </header>

      {view === "voices" ? (
        <>
          <section className="stats stats-headline">
            <article><span>{filteredStats.voices.toLocaleString()}</span><p>Filtered voices</p></article>
            <article><span>{filteredStats.online.toLocaleString()}</span><p>Online voices</p></article>
            <article><span>{filteredStats.offline.toLocaleString()}</span><p>Offline voices</p></article>
          </section>

          <section className="filters-wrap">
            <div className="filters-inline">
              <input
                className="search-always"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search voice id, language, country, script..."
              />
              <button type="button" className="toggle-btn filter-toggle-btn" onClick={() => setShowVoiceFilters((v) => !v)}>
                <span aria-hidden="true">{showVoiceFilters ? "▾" : "▸"}</span>
                {showVoiceFilters ? "Less filters" : "More filters"}
                {!showVoiceFilters && voiceActiveFilters ? (
                  <span className="active-pill">{voiceActiveFilters} active</span>
                ) : null}
              </button>
              {voiceActiveFilters ? (
                <button
                  type="button"
                  className="toggle-btn filter-clear-btn"
                  onClick={() => {
                    setSelectedModes([]);
                    setSelectedGenders([]);
                    setSelectedPlatforms([]);
                    setSelectedRuntimes([]);
                    setSelectedProviders([]);
                    setSelectedEngineFamilies([]);
                    setSelectedDistributionChannels([]);
                    setExcludedEngines([]);
                  }}
                >
                  Clear
                </button>
              ) : null}
            </div>
            {showVoiceFilters ? (
              <section className="controls">
                <details className="check-filter" open>
                  <summary>Mode {selectedModes.length ? `(${selectedModes.length})` : ""}</summary>
                  <div className="check-list">
                    {["online", "offline"].map((item) => (
                      <label key={`mode-${item}`}>
                        <input
                          type="checkbox"
                          checked={selectedModes.includes(item)}
                          onChange={() => setSelectedModes((prev) => toggleSelection(prev, item))}
                        />
                        {item}
                      </label>
                    ))}
                  </div>
                </details>
                <details className="check-filter" open>
                  <summary>Gender {selectedGenders.length ? `(${selectedGenders.length})` : ""}</summary>
                  <div className="check-list">
                    {genderOptions.filter((item) => item !== "all").map((item) => (
                      <label key={`gender-${item}`}>
                        <input
                          type="checkbox"
                          checked={selectedGenders.includes(item)}
                          onChange={() => setSelectedGenders((prev) => toggleSelection(prev, item))}
                        />
                        {item}
                      </label>
                    ))}
                  </div>
                </details>
                <details className="check-filter">
                  <summary>Platform {selectedPlatforms.length ? `(${selectedPlatforms.length})` : ""}</summary>
                  <div className="check-list">
                    {platformOptions.filter((item) => item !== "all").map((item) => (
                      <label key={`platform-${item}`}>
                        <input
                          type="checkbox"
                          checked={selectedPlatforms.includes(item)}
                          onChange={() => setSelectedPlatforms((prev) => toggleSelection(prev, item))}
                        />
                        {item}
                      </label>
                    ))}
                  </div>
                </details>
                <details className="check-filter">
                  <summary>Runtime {selectedRuntimes.length ? `(${selectedRuntimes.length})` : ""}</summary>
                  <div className="check-list">
                    {runtimeOptions.filter((item) => item !== "all").map((item) => (
                      <label key={`runtime-${item}`}>
                        <input
                          type="checkbox"
                          checked={selectedRuntimes.includes(item)}
                          onChange={() => setSelectedRuntimes((prev) => toggleSelection(prev, item))}
                        />
                        {item}
                      </label>
                    ))}
                  </div>
                </details>
                <details className="check-filter">
                  <summary>Provider {selectedProviders.length ? `(${selectedProviders.length})` : ""}</summary>
                  <div className="check-list">
                    {providerOptions.filter((item) => item !== "all").map((item) => (
                      <label key={`provider-${item}`}>
                        <input
                          type="checkbox"
                          checked={selectedProviders.includes(item)}
                          onChange={() => setSelectedProviders((prev) => toggleSelection(prev, item))}
                        />
                        {item}
                      </label>
                    ))}
                  </div>
                </details>
                <details className="check-filter">
                  <summary>Engine Family {selectedEngineFamilies.length ? `(${selectedEngineFamilies.length})` : ""}</summary>
                  <div className="check-list">
                    {engineFamilyOptions.filter((item) => item !== "all").map((item) => (
                      <label key={`engine-family-${item}`}>
                        <input
                          type="checkbox"
                          checked={selectedEngineFamilies.includes(item)}
                          onChange={() => setSelectedEngineFamilies((prev) => toggleSelection(prev, item))}
                        />
                        {humanizeToken(item)}
                      </label>
                    ))}
                  </div>
                </details>
                <details className="check-filter">
                  <summary>Distribution {selectedDistributionChannels.length ? `(${selectedDistributionChannels.length})` : ""}</summary>
                  <div className="check-list">
                    {distributionChannelOptions.filter((item) => item !== "all").map((item) => (
                      <label key={`distribution-${item}`}>
                        <input
                          type="checkbox"
                          checked={selectedDistributionChannels.includes(item)}
                          onChange={() => setSelectedDistributionChannels((prev) => toggleSelection(prev, item))}
                        />
                        {humanizeToken(item)}
                      </label>
                    ))}
                  </div>
                </details>
                <details className="check-filter">
                  <summary>Exclude Engine {excludedEngines.length ? `(${excludedEngines.length})` : ""}</summary>
                  <div className="check-list">
                    {engineOptions.map((item) => (
                      <label key={`exclude-engine-${item}`}>
                        <input
                          type="checkbox"
                          checked={excludedEngines.includes(item)}
                          onChange={() => setExcludedEngines((prev) => toggleSelection(prev, item))}
                        />
                        {item}
                      </label>
                    ))}
                  </div>
                </details>
              </section>
            ) : null}
          </section>

          <div className="map-toggle-row">
            <button
              type="button"
              className="toggle-btn map-toggle-btn"
              onClick={() => {
                setShowMap((v) => !v);
                if (!showMap) setMapAutoCollapsed(false);
              }}
            >
              {showMap ? "Hide map" : "Show map"}
            </button>
          </div>
          {showMap ? (
            <section className="map-wrap" ref={mapWrapRef}>
              <MapContainer center={[20, 5]} zoom={2} minZoom={2} maxZoom={7} worldCopyJump className="map">
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                {mapPoints.map((point) => (
                  <CircleMarker
                    key={`${point.country_code}-${point.latitude}-${point.longitude}`}
                    center={[point.latitude, point.longitude]}
                    radius={bubbleRadius(point.count, maxBubble)}
                    pathOptions={{ color: "#ef8a62", fillColor: "#67a9cf", fillOpacity: 0.6, weight: 1.2 }}
                  >
                    <Popup>
                      <strong>{point.country_name}</strong><br />
                      {point.count} voices<br />
                      Online: {point.online_count}, Offline: {point.offline_count}
                    </Popup>
                  </CircleMarker>
                ))}
              </MapContainer>
            </section>
          ) : null}

          <section className="results">
            <div className="results-header">
              <h2>Voices</h2>
              <div className="results-controls voice-layout-controls">
                <p>{filteredVoices.length.toLocaleString()} match filter</p>
                <button
                  type="button"
                  className={`toggle-btn view-toggle-btn ${voiceLayout === "grid" ? "active" : ""}`}
                  onClick={() => setVoiceLayout("grid")}
                >
                  <span aria-hidden="true">□</span> Grid
                </button>
                <button
                  type="button"
                  className={`toggle-btn view-toggle-btn ${voiceLayout === "list" ? "active" : ""}`}
                  onClick={() => setVoiceLayout("list")}
                >
                  <span aria-hidden="true">≡</span> List
                </button>
              </div>
            </div>
            <Pagination
              page={voicePage}
              pageCount={voicePageCount}
              onPrev={() => setVoicePage((p) => Math.max(1, p - 1))}
              onNext={() => setVoicePage((p) => Math.min(voicePageCount, p + 1))}
            />
            {voiceLayout === "list" ? (
              <div className="voice-list-header" aria-hidden="true">
                <span>Name / ID</span>
                <span>Language</span>
                <span>Gender</span>
                <span>Mode</span>
                <span>Runtime / Provider</span>
                <span>Preview</span>
              </div>
            ) : null}
            <div className={`voice-grid compact ${voiceLayout === "list" ? "list" : ""}`}>
              {visibleVoices.map((voice) => (
                <button
                  key={voice.voice_key}
                  type="button"
                  className={`voice-card compact-card ${voiceLayout === "grid" ? "grid-card" : "list-card"}`}
                  onClick={() => setSelectedVoice(voice)}
                >
                  {voiceLayout === "list" ? (
                    <>
                      <div className="voice-col voice-main">
                        <h3>{voice.name}</h3>
                        <p className="meta"><code>{voice.id}</code></p>
                      </div>
                      <p className="meta voice-col">{voice.language_display || voice.language_name || "Unknown language"}</p>
                      <p className="meta voice-col">{voice.gender || "Unknown"}</p>
                      <p className="meta voice-col">
                        <span className={`mode-chip ${toLower(voice.mode) === "online" ? "online" : "offline"}`}>
                          {voice.mode || "unknown"}
                        </span>
                      </p>
                      <p className="meta voice-col">{voice.runtime || "Unknown"} · {voice.provider || "Unknown"}</p>
                      <div className="meta voice-col preview-inline">
                        {previewItems(voice).length ? (
                          <audio controls preload="none" src={previewItems(voice)[0].url} />
                        ) : (
                          <span className="muted">None</span>
                        )}
                      </div>
                    </>
                  ) : (
                    <>
                      <span className={`mode-chip grid-mode-badge ${toLower(voice.mode) === "online" ? "online" : "offline"}`}>
                        {voice.mode || "unknown"}
                      </span>
                      <h3>{voice.name}</h3>
                      <p className="meta"><code>{voice.id}</code></p>
                      <p className="meta">{voice.language_display || voice.language_name || "Unknown language"}</p>
                      <p className="meta">{voice.gender || "Unknown"} · {voice.runtime || "Unknown"}</p>
                    </>
                  )}
                </button>
              ))}
            </div>
          </section>
        </>
      ) : (
        <section className="results">
          <div className="results-header">
            <h2>Assistive Technology Solutions</h2>
            <div className="results-controls">
              <select value={solutionVoiceOrigin} onChange={(e) => setSolutionVoiceOrigin(e.target.value)}>
                {solutionVoiceOriginOptions.map((item) => (
                  <option key={item} value={item}>
                    {voiceOriginLabel(item)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="view-switch">
            <button
              type="button"
              className={assistiveSubtab === "aac" ? "active" : ""}
              onClick={() => setAssistiveSubtab("aac")}
            >
              AAC
            </button>
            <button
              type="button"
              className={assistiveSubtab === "screenreader" ? "active" : ""}
              onClick={() => setAssistiveSubtab("screenreader")}
            >
              Screenreaders
            </button>
          </div>
          {assistiveSubtab === "screenreader" ? (
            <p className="status error">
              Screenreader compatibility data is currently mocked/experimental and not production-validated yet.
            </p>
          ) : null}
          <section className="filters-wrap">
            <div className="filters-inline">
              <input
                className="search-always"
                type="search"
                value={accLanguageQuery}
                onChange={(e) => setAccLanguageQuery(e.target.value)}
                placeholder="Search language (for solution match counts)"
              />
              <button type="button" className="toggle-btn filter-toggle-btn" onClick={() => setShowAssistiveFilters((v) => !v)}>
                <span aria-hidden="true">{showAssistiveFilters ? "▾" : "▸"}</span>
                {showAssistiveFilters ? "Less filters" : "More filters"}
                {!showAssistiveFilters && assistiveActiveFilters ? (
                  <span className="active-pill">{assistiveActiveFilters} active</span>
                ) : null}
              </button>
            </div>
            {showAssistiveFilters ? (
              <section className="controls accessibility-controls">
                <select value={accMode} onChange={(e) => setAccMode(e.target.value)}>
                  <option value="all">All modes</option>
                  <option value="online">Online</option>
                  <option value="offline">Offline</option>
                </select>
                <select value={accPlatform} onChange={(e) => setAccPlatform(e.target.value)}>
                  <option value="all">All platforms</option>
                  <option value="windows">Windows</option>
                  <option value="ios">iOS</option>
                  <option value="android">Android</option>
                  <option value="linux">Linux</option>
                  <option value="macos">macOS</option>
                </select>
              </section>
            ) : null}
          </section>
          {assistiveSubtab === "aac" && voiceBankingProviders.length ? (
            <section className="results">
              <details className="voice-banking-panel">
                <summary>
                  Voice Banking & Cloning Support ({voiceBankingProviders.length} providers)
                </summary>
                <p className="meta">
                  Uses current AAC filters, including language search, mode, and platform.
                </p>
                <div className="voice-grid compact">
                  {voiceBankingProviders.map((item) => (
                    <article key={item.provider} className="voice-card">
                      <h3>{item.provider}</h3>
                      <p className="meta">Apps: {item.appCount}</p>
                      <p className="meta">Origins: {item.voiceOrigins.join(", ")}</p>
                      <p className="meta">Supports: {item.apps.join(", ")}</p>
                    </article>
                  ))}
                </div>
              </details>
            </section>
          ) : null}
          <Pagination
            page={solutionPage}
            pageCount={solutionPageCount}
            onPrev={() => setSolutionPage((p) => Math.max(1, p - 1))}
            onNext={() => setSolutionPage((p) => Math.min(solutionPageCount, p + 1))}
          />
          <div className="voice-grid compact">
            {visibleSolutions.map((solution) => (
              <button
                key={solution.id}
                type="button"
                className="voice-card compact-card solution-card"
                onClick={() => {
                  setSelectedSolutionId(solution.id);
                  setSolutionModalQuery("");
                  setSolutionModalPage(1);
                }}
              >
                <h3>{solution.name}</h3>
                <p className="meta">{solution.vendor || "Unknown vendor"} · {solution.category}</p>
                <p className="meta">Matches in current accessibility filters: {solution.total.toLocaleString()}</p>
                <p className="meta">{supportParts(solution)}</p>
                {solution.voiceOrigins?.length ? (
                  <p className="meta">Voice origin: {solution.voiceOrigins.join(", ")}</p>
                ) : null}
                {(solution.requiresEnrollment || solution.requiresUserAsset) ? (
                  <p className="meta">
                    {solution.requiresEnrollment ? "Requires enrollment" : "No enrollment required"} ·{" "}
                    {solution.requiresUserAsset ? "Requires user voice asset" : "No user asset required"}
                  </p>
                ) : null}
              </button>
            ))}
          </div>
        </section>
      )}

      {selectedVoice ? (
        <div className="modal-backdrop" onClick={() => setSelectedVoice(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="results-header">
              <h2>{selectedVoice.name}</h2>
              <button className="modal-close-btn" type="button" onClick={() => setSelectedVoice(null)}>Close</button>
            </div>
            <p className="meta"><code>{selectedVoice.id}</code></p>
            <p className="meta">{selectedVoice.runtime || "Unknown"} · {selectedVoice.provider || "Unknown"}</p>
            <p className="meta">{selectedVoice.engine_family || "unknown"} · {selectedVoice.distribution_channel || "unknown"}</p>
            <p className="meta">{selectedVoice.language_display || selectedVoice.language_name || "Unknown language"}</p>
            <p className="meta">Country: {selectedVoice.country_name} ({selectedVoice.country_code})</p>
            <p className="meta">Gender: {selectedVoice.gender || "Unknown"}</p>
            {previewItems(selectedVoice).length ? (
              <details className="preview-list" open>
                <summary>Previews ({previewItems(selectedVoice).length})</summary>
                {previewItems(selectedVoice).map((item, idx) => (
                  <div key={`${selectedVoice.voice_key}-preview-${idx}`} className="preview-item">
                    <div className="preview-label">{item.language_code || "default"} · {item.source || "preview"}</div>
                    <audio controls preload="none" src={item.url} />
                  </div>
                ))}
              </details>
            ) : null}
          </div>
        </div>
      ) : null}

      {selectedSolution ? (
        <div className="modal-backdrop" onClick={() => setSelectedSolutionId(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="results-header">
              <h2>{selectedSolution.name}</h2>
              <button className="modal-close-btn" type="button" onClick={() => setSelectedSolutionId(null)}>Close</button>
            </div>
            <p className="meta">{selectedSolution.vendor || "Unknown vendor"} · {selectedSolution.category}</p>
            <p className="meta">{supportParts(selectedSolution)}</p>
            <p className="meta">
              Voice origin: {selectedSolution.voiceOrigins?.length ? selectedSolution.voiceOrigins.join(", ") : "not set"}
            </p>
            {(selectedSolution.requiresEnrollment || selectedSolution.requiresUserAsset) ? (
              <p className="meta">
                {selectedSolution.requiresEnrollment ? "Requires enrollment" : "No enrollment required"} ·{" "}
                {selectedSolution.requiresUserAsset ? "Requires user voice asset" : "No user asset required"}
              </p>
            ) : null}
            {Array.isArray(selectedSolution.links) && selectedSolution.links.length ? (
              <div className="meta">
                Links:{" "}
                {selectedSolution.links.map((link, idx) => (
                  <span key={`${selectedSolution.id}-link-${idx}`}>
                    <a href={link} target="_blank" rel="noreferrer">{link}</a>
                    {idx < selectedSolution.links.length - 1 ? " · " : ""}
                  </span>
                ))}
              </div>
            ) : null}
            <p className="meta">
              Matching voices in current accessibility filters: {selectedSolution.matchedVoices.length.toLocaleString()}
              {accLanguageQuery.trim() ? ` (language search: "${accLanguageQuery.trim()}")` : ""}
            </p>
            <section className="controls accessibility-controls">
              <select value={accMode} onChange={(e) => setAccMode(e.target.value)}>
                <option value="all">All modes</option>
                <option value="online">Online</option>
                <option value="offline">Offline</option>
              </select>
              <select value={accPlatform} onChange={(e) => setAccPlatform(e.target.value)}>
                <option value="all">All platforms</option>
                {platformOptions
                  .filter((item) => item !== "all")
                  .map((item) => <option key={`modal-platform-${item}`} value={item}>{item}</option>)}
              </select>
              <input
                type="search"
                value={solutionModalQuery}
                onChange={(e) => setSolutionModalQuery(e.target.value)}
                placeholder="Search matched voices by id/name/language/engine/provider"
              />
            </section>
            <Pagination
              page={solutionModalPage}
              pageCount={solutionModalPageCount}
              onPrev={() => setSolutionModalPage((p) => Math.max(1, p - 1))}
              onNext={() => setSolutionModalPage((p) => Math.min(solutionModalPageCount, p + 1))}
            />
            <div className="voice-grid compact">
              {visibleSolutionModalMatches.map((item) => {
                const v = item.voice;
                const previews = previewItems(v);
                return (
                  <article key={`${selectedSolution.id}-${v.voice_key}`} className="voice-card">
                    <h3>{v.name}</h3>
                    <p className="meta"><code>{v.id}</code></p>
                    <p className="meta">{v.language_display || v.language_name || "Unknown language"}</p>
                    <p className="meta">{v.engine} · {v.runtime || "Unknown"} · {v.provider || "Unknown"}</p>
                    <p className="meta">Match path: {item.reason || "rule"} </p>
                    {previews.length ? (
                      <audio controls preload="none" src={previews[0].url} />
                    ) : null}
                  </article>
                );
              })}
            </div>
            {selectedSolutionFilteredMatches.length > SOLUTION_MODAL_PAGE_SIZE ? (
              <p className="meta">
                Showing page {solutionModalPage} of {solutionModalPageCount} matched voices.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <footer className="footer-note">
        <p>
          Data source:{" "}
          <a href="https://tts-voice-catalog.vercel.app/" target="_blank" rel="noreferrer">
            tts-voice-catalog.vercel.app
          </a>
          . Dataset is collected via <code>py3-tts-wrapper</code>, enriched, harmonized into SQLite,
          and exported for this static site from <code>data/static/voices-site.json</code>.
        </p>
      </footer>
    </main>
  );
}
