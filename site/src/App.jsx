import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";

const MAX_RESULTS = 250;

function bubbleRadius(value, max) {
  if (max <= 0) {
    return 6;
  }
  return Math.max(5, Math.min(36, 6 + (Math.sqrt(value) / Math.sqrt(max)) * 30));
}

function toLower(value) {
  return String(value || "").toLowerCase();
}

function pct(value, total) {
  if (!total) {
    return "0%";
  }
  return `${((value / total) * 100).toFixed(1)}%`;
}

function pctOrNA(value, total) {
  if (!total) {
    return "n/a";
  }
  return pct(value, total);
}

function formatTimestamp(value) {
  if (!value) {
    return "Unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
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
  if (!query.includes("arab")) {
    return false;
  }
  const script = toLower(voice.script);
  const writtenScript = toLower(voice.written_script);
  return script === "arab" || writtenScript.includes("arab");
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

export default function App() {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("all");
  const [gender, setGender] = useState("all");
  const [engine, setEngine] = useState("all");
  const [platform, setPlatform] = useState("all");

  useEffect(() => {
    const url = `${import.meta.env.BASE_URL}data/voices-site.json?v=${Date.now()}`;
    fetch(url, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load ${url}: ${res.status}`);
        }
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

  const engineOptions = useMemo(() => {
    return ["all", ...Object.keys(payload?.facets?.engines || {}).sort((a, b) => a.localeCompare(b))];
  }, [payload]);

  const platformOptions = useMemo(() => {
    return ["all", ...Object.keys(payload?.facets?.platforms || {}).sort((a, b) => a.localeCompare(b))];
  }, [payload]);

  const genderOptions = useMemo(() => {
    return ["all", ...Object.keys(payload?.facets?.genders || {}).sort((a, b) => a.localeCompare(b))];
  }, [payload]);

  const filteredVoices = useMemo(() => {
    const q = toLower(query).trim();
    return voices.filter((voice) => {
      if (mode !== "all" && voice.mode !== mode) {
        return false;
      }
      if (gender !== "all" && toLower(voice.gender) !== toLower(gender)) {
        return false;
      }
      if (engine !== "all" && voice.engine !== engine) {
        return false;
      }
      if (platform !== "all" && voice.platform !== platform) {
        return false;
      }
      if (!q) {
        return true;
      }

      const haystack = [
        voice.id,
        voice.name,
        voice.country_code,
        voice.country_name,
        voice.language_name,
        voice.language_display,
        voice.script,
        voice.written_script,
        ...(voice.language_codes || []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (haystack.includes(q)) {
        return true;
      }

      // "arabic" should also match voices for languages written in Arabic script.
      return isArabicScriptMatch(q, voice);
    });
  }, [voices, query, mode, gender, engine, platform]);

  const filteredStats = useMemo(() => {
    const online = filteredVoices.filter((v) => v.mode === "online").length;
    const offline = filteredVoices.length - online;
    return {
      voices: filteredVoices.length,
      online,
      offline,
    };
  }, [filteredVoices]);

  const mapPoints = useMemo(() => {
    const grouped = new Map();
    for (const voice of filteredVoices) {
      if (voice.latitude == null || voice.longitude == null) {
        continue;
      }
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
      if (voice.mode === "online") {
        item.online_count += 1;
      } else {
        item.offline_count += 1;
      }
      item.latitude_sum += Number(voice.latitude);
      item.longitude_sum += Number(voice.longitude);
      item.points += 1;
      const lang =
        voice.language_display ||
        voice.language_name ||
        (Array.isArray(voice.language_codes) && voice.language_codes.length ? voice.language_codes[0] : null) ||
        "Unknown";
      item.languages.set(lang, (item.languages.get(lang) || 0) + 1);
    }
    const out = [];
    for (const item of grouped.values()) {
      if (!item.points) {
        continue;
      }
      out.push({
        country_code: item.country_code,
        country_name: item.country_name,
        count: item.count,
        online_count: item.online_count,
        offline_count: item.offline_count,
        latitude: item.latitude_sum / item.points,
        longitude: item.longitude_sum / item.points,
        top_languages: Array.from(item.languages.entries())
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5)
          .map(([name, count]) => ({ name, count })),
      });
    }
    return out.sort((a, b) => b.count - a.count);
  }, [filteredVoices]);

  const maxBubble = useMemo(() => {
    return mapPoints.reduce((max, point) => Math.max(max, point.count), 0);
  }, [mapPoints]);

  if (loading) {
    return <main className="app"><p className="status">Loading voices atlas...</p></main>;
  }
  if (error) {
    return <main className="app"><p className="status error">{error}</p></main>;
  }

  return (
    <main className="app">
      <header className="hero">
        <p className="kicker">TTS Dataset</p>
        <h1>Global Voice Atlas</h1>
        <p className="lede">
          Explore voices by geography, voice id, language, country, mode, and engine.
        </p>
        <p className="coverage-inline">
          Updated {formatTimestamp(generatedAt)}. Speaker coverage: online {pctOrNA(languageSpeakersOnline, languageSpeakersTotal)},
          offline {pctOrNA(languageSpeakersOffline, languageSpeakersTotal)}, total {pctOrNA(languageSpeakersCovered, languageSpeakersTotal)}
          . Languages with no TTS: {referenceLanguagesNoTTS}/{referenceLanguagesTotal} ({pctOrNA(referenceLanguagesNoTTS, referenceLanguagesTotal)}).
          Languages with no offline TTS: {referenceLanguagesNoOfflineTTS}/{referenceLanguagesTotal} ({pctOrNA(referenceLanguagesNoOfflineTTS, referenceLanguagesTotal)}).
        </p>
      </header>

      <section className="stats stats-headline">
        <article><span>{filteredStats.voices.toLocaleString()}</span><p>Filtered voices</p></article>
        <article><span>{filteredStats.online.toLocaleString()}</span><p>Online voices</p></article>
        <article><span>{filteredStats.offline.toLocaleString()}</span><p>Offline voices</p></article>
      </section>

      <section className="controls">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search voice id, language, country, script..."
        />
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="all">All modes</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
        </select>
        <select value={gender} onChange={(e) => setGender(e.target.value)}>
          {genderOptions.map((item) => <option key={item} value={item}>{item === "all" ? "All genders" : item}</option>)}
        </select>
        <select value={engine} onChange={(e) => setEngine(e.target.value)}>
          {engineOptions.map((item) => <option key={item} value={item}>{item === "all" ? "All engines" : item}</option>)}
        </select>
        <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
          {platformOptions.map((item) => <option key={item} value={item}>{item === "all" ? "All platforms" : item}</option>)}
        </select>
      </section>

      <section className="map-wrap">
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
              pathOptions={{
                color: "#ef8a62",
                fillColor: "#67a9cf",
                fillOpacity: 0.6,
                weight: 1.2,
              }}
            >
              <Popup>
                <strong>{point.country_name}</strong><br />
                {point.count} voices<br />
                Online: {point.online_count}, Offline: {point.offline_count}
                {point.top_languages.length ? (
                  <>
                    <br />
                    Top languages:
                    <ul>
                      {point.top_languages.map((lang) => (
                        <li key={`${point.country_code}-${lang.name}`}>{lang.name} ({lang.count})</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </section>

      <section className="results">
        <div className="results-header">
          <h2>Voices</h2>
          <p>{filteredVoices.length.toLocaleString()} match filter</p>
        </div>
        <div className="voice-grid">
          {filteredVoices.slice(0, MAX_RESULTS).map((voice) => {
            const previews = previewItems(voice);
            const platformLabel = voice.platform_display || voice.platform;
            return (
              <article key={voice.voice_key} className="voice-card">
                <h3>{voice.name}</h3>
                <p className="meta"><code>{voice.id}</code></p>
                <p className="meta">{voice.engine} · {voice.mode} · {platformLabel}</p>
                <p className="meta">{voice.country_name} ({voice.country_code})</p>
                <p className="meta">{(voice.language_codes || []).join(", ") || "Unknown language"}</p>
                <p className="meta">Gender: {voice.gender || "Unknown"}</p>

                {previews.length ? (
                  <details className="preview-list">
                    <summary>Previews ({previews.length})</summary>
                    {previews.map((item, idx) => (
                      <div key={`${voice.voice_key}-preview-${idx}`} className="preview-item">
                        <div className="preview-label">
                          {item.language_code || "default"} · {item.source || "preview"}
                        </div>
                        <audio controls preload="none" src={item.url} />
                      </div>
                    ))}
                  </details>
                ) : null}
              </article>
            );
          })}
        </div>
        {filteredVoices.length > MAX_RESULTS ? (
          <p className="status">Showing first {MAX_RESULTS} results. Narrow your filters to see more.</p>
        ) : null}
      </section>

      <footer className="footer-note">
        <p>
          Data source:{" "}
          <a href="https://tts-voice-catalog.vercel.app/" target="_blank" rel="noreferrer">
            tts-voice-catalog.vercel.app
          </a>
          . Dataset is collected via <code>py3-tts-wrapper</code>, enriched, harmonized into SQLite,
          and exported for this static site from <code>data/static/voices-site.json</code>.
        </p>
        <p>
          Methodology and pipeline details:{" "}
          <a
            href="https://github.com/willwade/TTS-Dataset/blob/main/README.md"
            target="_blank"
            rel="noreferrer"
          >
            repository README
          </a>
          .
        </p>
        <p>
          Coverage percentages are weighted by language speaker estimates (mapped from language codes), so they are
          a proxy index and not exact unique-person reach.
        </p>
      </footer>
    </main>
  );
}
