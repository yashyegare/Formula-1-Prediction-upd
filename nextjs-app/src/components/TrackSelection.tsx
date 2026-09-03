import React, { useEffect, useRef, useState } from "react";

const TRACKS = [
    { name: "Monaco", flag: "\u{1F1F2}\u{1F1E8}", country: "Monaco", length: "3.337 km", svg: "/circuits/monaco.svg" },
    { name: "Silverstone", flag: "\u{1F1EC}\u{1F1E7}", country: "United Kingdom", length: "5.891 km", svg: "/circuits/silverstone.svg" },
    { name: "Suzuka", flag: "\u{1F1EF}\u{1F1F5}", country: "Japan", length: "5.807 km", svg: "/circuits/suzuka.svg" },
    { name: "Spa", flag: "\u{1F1E7}\u{1F1EA}", country: "Belgium", length: "7.004 km", svg: "/circuits/spa.svg" },
    { name: "Interlagos", flag: "\u{1F1E7}\u{1F1F7}", country: "Brazil", length: "4.309 km", svg: "/circuits/interlagos.svg" },
];

const TrackCard = ({ track, isSelected, onClick }: {
    track: typeof TRACKS[0];
    isSelected: boolean;
    onClick: () => void;
}) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const dotRef = useRef<SVGCircleElement>(null);
    const animRef = useRef<number>(0);
    const progressRef = useRef(0);

    useEffect(() => {
        const container = containerRef.current;
        const dot = dotRef.current;
        if (!container || !dot) return;

        fetch(track.svg)
            .then(r => r.text())
            .then(svgText => {
                const wrapper = container.querySelector(".svg-wrapper");
                if (!wrapper) return;

                const parser = new DOMParser();
                const doc = parser.parseFromString(svgText, "image/svg+xml");
                const svgEl = doc.querySelector("svg");
                const pathEl = doc.querySelector("path");
                if (!svgEl || !pathEl) return;

                const viewBox = svgEl.getAttribute("viewBox") || "0 0 300 200";
                const d = pathEl.getAttribute("d") || "";

                const newSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                newSvg.setAttribute("viewBox", viewBox);
                newSvg.setAttribute("fill", "none");
                newSvg.setAttribute("class", "w-full h-full");

                const glowPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
                glowPath.setAttribute("d", d);
                glowPath.setAttribute("stroke", isSelected ? "#22c55e" : "#52525b");
                glowPath.setAttribute("stroke-width", "10");
                glowPath.setAttribute("stroke-linecap", "round");
                glowPath.setAttribute("stroke-linejoin", "round");
                glowPath.setAttribute("fill", "none");
                glowPath.setAttribute("opacity", isSelected ? "0.2" : "0.1");

                const trackPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
                trackPath.setAttribute("d", d);
                trackPath.setAttribute("stroke", isSelected ? "#22c55e" : "#71717a");
                trackPath.setAttribute("stroke-width", "2.5");
                trackPath.setAttribute("stroke-linecap", "round");
                trackPath.setAttribute("stroke-linejoin", "round");
                trackPath.setAttribute("fill", "none");

                newSvg.appendChild(glowPath);
                newSvg.appendChild(trackPath);

                const imgEl = wrapper.querySelector("img");
                if (imgEl) imgEl.remove();
                wrapper.appendChild(newSvg);

                const totalLength = trackPath.getTotalLength();
                let lastTime = 0;

                const animate = (time: number) => {
                    if (!lastTime) lastTime = time;
                    const delta = time - lastTime;
                    lastTime = time;
                    progressRef.current = (progressRef.current + delta / 3000) % 1;
                    const point = trackPath.getPointAtLength(progressRef.current * totalLength);
                    dot.setAttribute("cx", String(point.x));
                    dot.setAttribute("cy", String(point.y));
                    animRef.current = requestAnimationFrame(animate);
                };

                animRef.current = requestAnimationFrame(animate);
            })
            .catch(() => {});

        return () => cancelAnimationFrame(animRef.current);
    }, [isSelected, track.svg]);

    return (
        <button
            onClick={onClick}
            className={`group relative flex flex-col items-center rounded-2xl border-2 p-4 transition-all duration-200 cursor-pointer ${
                isSelected
                    ? "border-green-500 bg-green-500/10 shadow-lg shadow-green-500/20"
                    : "border-zinc-800 bg-zinc-900/60 hover:border-zinc-600 hover:bg-zinc-900"
            }`}
        >
            <div ref={containerRef} className="w-full aspect-[4/3] mb-3 flex items-center justify-center relative">
                <div className="svg-wrapper w-full h-full flex items-center justify-center">
                    <img src={track.svg} alt={track.name} className="w-full h-full object-contain opacity-40 group-hover:opacity-60 transition" />
                </div>
                <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ overflow: "visible" }}>
                    <circle ref={dotRef} r="3.5" fill={isSelected ? "#22c55e" : "#a1a1aa"} />
                    <circle r="6" fill={isSelected ? "#22c55e" : "#a1a1aa"} opacity="0.25">
                        <animate attributeName="r" values="5;8;5" dur="1.5s" repeatCount="indefinite" />
                        <animate attributeName="opacity" values="0.25;0.08;0.25" dur="1.5s" repeatCount="indefinite" />
                    </circle>
                </svg>
            </div>

            <div className="text-center mb-2">
                <div className="text-base font-bold text-white">{track.flag} {track.name}</div>
                <div className="text-[10px] text-zinc-500">{track.country} &middot; {track.length}</div>
            </div>

            <div className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all ${
                isSelected
                    ? "bg-green-500 text-white"
                    : "bg-green-500/15 text-green-400 border border-green-500/30"
            }`}>
                {isSelected ? "\u2713 Selected" : "Play Now"}
            </div>
        </button>
    );
};

const TrackSelection = ({ onSelectTrack, onFullscreen }: {
    onSelectTrack: (trackName: string) => void;
    onFullscreen: () => void;
}) => {
    const [selectedTrack, setSelectedTrack] = useState<string | null>(null);
    const [userName, setUserName] = useState("Racer");
    const [showWelcome, setShowWelcome] = useState(true);
    const [nameInput, setNameInput] = useState("");

    useEffect(() => {
        const stored = localStorage.getItem("dlr_username");
        if (stored) {
            setUserName(stored);
            setShowWelcome(false);
        }
    }, []);

    const handleNameSubmit = () => {
        const name = nameInput.trim() || "Racer";
        setUserName(name);
        localStorage.setItem("dlr_username", name);
        setShowWelcome(false);
    };

    const handlePlay = () => {
        if (selectedTrack) {
            localStorage.setItem("dlr_username", userName);
            onSelectTrack(selectedTrack);
        }
    };

    return (
        <div className="min-h-screen bg-[#0c0f1a] text-white relative">
            <button
                onClick={onFullscreen}
                className="absolute top-3 left-3 z-20 bg-white/90 hover:bg-white text-slate-700 px-3 py-1.5 rounded-full text-xs font-bold shadow-lg flex items-center gap-1.5 transition-all hover:scale-105"
            >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path>
                </svg>
                Fullscreen
            </button>

            <a
                href="/"
                className="absolute top-3 right-3 z-20 bg-white/10 hover:bg-white/20 text-zinc-300 hover:text-white px-3 py-1.5 rounded-full text-xs font-bold flex items-center gap-1.5 transition-all"
            >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M19 12H5M12 19l-7-7 7-7" />
                </svg>
                Race Predictor
            </a>

            <div className="max-w-4xl mx-auto px-4 pt-16 pb-8">
                {showWelcome && (
                    <div className="text-center animate-fadeIn">
                        <h1 className="text-3xl md:text-4xl font-bold mb-1">DrawLineRacing</h1>
                        <p className="text-zinc-400 text-lg mb-8">Welcome back!</p>
                        <div className="flex items-center justify-center gap-2 mb-2">
                            <span className="text-zinc-500 text-sm">Name:</span>
                            <input
                                type="text"
                                value={nameInput}
                                onChange={(e) => setNameInput(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && handleNameSubmit()}
                                className="bg-white/5 border border-white/10 rounded-xl px-4 py-2 text-white font-semibold outline-none w-48 text-center focus:border-green-500 transition-colors"
                                placeholder="Your name..."
                                autoFocus
                            />
                            <button
                                onClick={handleNameSubmit}
                                className="bg-green-500 hover:bg-green-400 text-white px-5 py-2 rounded-xl text-sm font-bold transition-colors"
                            >
                                Go
                            </button>
                        </div>
                    </div>
                )}

                {!showWelcome && (
                    <div className="animate-fadeIn">
                        <div className="text-center mb-8">
                            <h1 className="text-3xl md:text-4xl font-bold mb-1">
                                Welcome back, <span className="text-green-400">{userName}</span>!
                            </h1>
                            <p className="text-zinc-400 text-lg">Select Track</p>
                        </div>

                        <div className="flex justify-center mb-6">
                            <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-full px-4 py-2">
                                <div className="w-2 h-2 rounded-full bg-green-400" />
                                <span className="text-xs text-zinc-400">AI Opponents ON</span>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                            {TRACKS.map((track) => (
                                <TrackCard
                                    key={track.name}
                                    track={track}
                                    isSelected={selectedTrack === track.name}
                                    onClick={() => setSelectedTrack(track.name)}
                                />
                            ))}
                        </div>

                        {selectedTrack && (
                            <div className="flex justify-center mt-8 animate-fadeIn">
                                <button
                                    onClick={handlePlay}
                                    className="flex items-center gap-3 bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-400 hover:to-emerald-400 text-white px-8 py-3 rounded-xl font-bold text-lg shadow-lg shadow-green-500/25 transition-all hover:scale-105 active:scale-95"
                                >
                                    Play Now
                                </button>
                            </div>
                        )}

                        <div className="text-center mt-6">
                            <button
                                onClick={() => setShowWelcome(true)}
                                className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
                            >
                                Change Name
                            </button>
                        </div>
                    </div>
                )}
            </div>

            <style jsx>{`
                @keyframes fadeIn {
                    from { opacity: 0; transform: translateY(8px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                .animate-fadeIn {
                    animation: fadeIn 0.4s ease-out;
                }
            `}</style>
        </div>
    );
};

export default TrackSelection;
