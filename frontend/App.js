import React, { useState, useRef, useEffect } from "react";
import ReactAudioPlayer from "react-audio-player";
import "./App.css";

const BACKEND = "http://127.0.0.1:8000";

function App() {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [translated, setTranslated] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const [languages, setLanguages] = useState([]);
  const [targetLang, setTargetLang] = useState("fr");
  const [loading, setLoading] = useState(false);

  const recognitionRef = useRef(null);

  // Load languages from backend
  useEffect(() => {
    fetch(`${BACKEND}/languages`)
      .then(res => res.json())
      .then(data => setLanguages(data.languages || []))
      .catch(() => setLanguages([]));
  }, []);

  const startListening = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      alert("Your browser doesn't support microphone speech recognition. Please use Chrome.");
      return;
    }
    const recognition = new SR();
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = true;

    recognition.onresult = (event) => {
      let interim = "";
      let finalText = transcript;
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i];
        if (res.isFinal) finalText += res[0].transcript + " ";
        else interim += res[0].transcript;
      }
      setTranscript(finalText + interim);
    };

    recognition.onerror = () => stopListening();
    recognition.onend = () => setListening(false);

    recognition.start();
    recognitionRef.current = recognition;
    setListening(true);
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
    setListening(false);
  };

  const handleTranslate = async () => {
    if (!transcript.trim()) {
      alert("Please speak first — no text to translate.");
      return;
    }
    setLoading(true);
    setTranslated("");
    setAudioUrl("");

    try {
      const res = await fetch(`${BACKEND}/translate_tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: transcript,
          target_lang: targetLang,
          source_lang: "auto"
        })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.error || "Translation failed.");
      } else {
        setTranslated(data.translated_text);
        setAudioUrl(`${BACKEND}${data.audio_url}`);
      }
    } catch (e) {
      alert("Server error. Is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  const clearAll = () => {
    setTranscript("");
    setTranslated("");
    setAudioUrl("");
  };

  return (
    <div className="App">
      <header>
        <h1>🩺 Healthcare Translator</h1>
        <p className="subtitle">Speak, translate, and listen instantly</p>
      </header>

      <div className="controls">
        {!listening ? (
          <button className="primary" onClick={startListening}>🎤 Start Listening</button>
        ) : (
          <button className="stop" onClick={stopListening}>⏹ Stop</button>
        )}

        <select value={targetLang} onChange={(e) => setTargetLang(e.target.value)}>
          {languages.map((l) => (
            <option key={l.code} value={l.code}>
              {l.name} ({l.code})
            </option>
          ))}
        </select>

        <button className="primary" onClick={handleTranslate} disabled={loading}>
          {loading ? "Translating..." : "🌐 Translate & Speak"}
        </button>

        <button className="secondary" onClick={clearAll}>🧹 Clear</button>
      </div>

      <div className="panel">
        <h3>🗣 Original Transcript</h3>
        <p>{transcript || "Waiting for your speech..."}</p>
      </div>

      <div className="panel">
        <h3>🌎 Translated Text</h3>
        <p>{translated || "No translation yet."}</p>
      </div>

      {audioUrl && (
        <div className="panel">
          <h3>🔊 Audio Playback</h3>
          <ReactAudioPlayer src={audioUrl} controls autoPlay />
        </div>
      )}
    </div>
  );
}

export default App;
