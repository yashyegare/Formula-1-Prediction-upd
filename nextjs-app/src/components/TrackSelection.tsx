import React, { useEffect, useRef, useState } from "react";

/* ── Track data ── */
const TRACKS = [
    { name: "Monaco", flag: "🇲🇨", country: "Monaco", length: "3.337 km", status: "play" as const },
    { name: "Silverstone", flag: "🇬🇧", country: "United Kingdom", length: "5.891 km", status: "play" as const },
    { name: "Suzuka", flag: "🇯🇵", country: "Japan", length: "5.807 km", status: "play" as const },
    { name: "Spa", flag: "🇧🇪", country: "Belgium", length: "7.004 km", status: "play" as const },
    { name: "Interlagos", flag: "🇧🇷", country: "Brazil", length: "4.309 km", status: "play" as const },
];

/* ── SVG track outlines for previews ── */
const TRACK_SVGS: Record<string, string> = {
    Monaco: "M100,145 L85,130 L75,110 L70,90 L68,75 L72,60 L80,48 L92,40 L105,38 L118,42 L128,50 L132,62 L130,75 L122,85 L110,90 L100,92 L92,88 L88,80 L90,70 L96,62 L105,58 L112,62 L115,70 L112,78 L105,82 L100,85 L118,90 L128,95 L135,105 L132,118 L122,130 L110,140 L100,145 Z",
    Silverstone: "M80,30 L110,25 L140,28 L165,38 L180,55 L185,75 L178,95 L165,110 L145,125 L120,135 L95,138 L70,132 L50,120 L38,105 L32,85 L35,65 L45,48 L58,36 L80,30 Z",
    Suzuka: "M60,30 L80,40 L95,55 L85,70 L70,75 L60,68 L55,55 L60,42 L75,38 L90,45 L100,58 L105,75 L100,90 L88,100 L75,108 L65,118 L60,132 L65,145 L80,152 L100,150 L118,142 L130,130 L135,115 L130,100 L118,92 L108,88 L115,78 L125,70 L140,65 L155,68 L165,78 L168,92 L162,105 L150,112 L138,108 L130,100",
    Spa: "M50,20 L65,18 L75,25 L78,38 L75,50 L68,58 L60,62 L55,70 L52,82 L48,95 L42,108 L38,122 L40,135 L48,145 L58,150 L68,148 L78,142 L85,132 L88,120 L85,108 L78,100 L68,95 L58,92 L50,88 L45,80 L42,70 L45,58 L52,50 L60,45 L68,42 L75,45 L78,55 L75,65 L68,72 L58,75 L50,72 L45,65 L42,55 L45,45 L52,38 L60,35 L68,38",
    Interlagos: "M155,45 L140,50 L125,58 L112,68 L105,80 L100,92 L95,105 L85,115 L72,120 L58,118 L48,110 L42,98 L40,85 L44,72 L52,62 L62,55 L75,50 L88,48 L100,50 L112,55 L122,62 L128,72 L125,82 L118,88 L108,90 L98,88 L90,82 L85,72 L85,62 L90,52 L100,48 L112,46 L125,48 L138,52 L148,58 L155,45 Z",
};

/* ── Animated SVG Track Preview ── */
const TrackCard = ({ track, isSelected, onClick }: {
    track: typeof TRACKS[0];
    isSelected: boolean;
    onClick: () => void;
}) => {
    const pathRef = useRef<SVGPathElement>(null);
    const dotRef = useRef<SVGCircleElement>(null);
    const animRef = useRef<number>(0);
    const progressRef = useRef(0);

    useEffect(() => {
        const path = pathRef.current;
        const dot = dotRef.current;
        if (!path || !dot) return;

        const totalLength = path.getTotalLength();
        let lastTime = 0;

        const animate = (time: number) => {
            if (!lastTime) lastTime = time;
            const delta = time - lastTime;
            lastTime = time;
            progressRef.current = (progressRef.current + delta / 2500) % 1;
            const point = path.getPointAtLength(progressRef.current * totalLength);
            dot.setAttribute("cx", String(point.x));
            dot.setAttribute("cy", String(point.y));
            animRef.current = requestAnimationFrame(animate);
        };

        animRef.current = requestAnimationFrame(animate);
        return () => cancelAnimationFrame(animRef.current);
    }, []);

    const svgPath = TRACK_SVGS[track.name];

    return (
        <button
            onClick={onClick}
            className={`group relative flex flex-col items-center rounded-2xl border-2 p-4 transition-all duration-200 cursor-pointer ${
                isSelected
                    ? "border-green-500 bg-green-500/10 shadow-lg shadow-green-500/20"
                    : "border-zinc-800 bg-zinc-900/60 hover:border-zinc-600 hover:bg-zinc-900"
            }`}
        >
            {/* Track SVG */}
            <div className="w-full aspect-[4/3] mb-3 flex items-center justify-center">
                <svg viewBox="0 0 200 160" className="w-full h-full" fill="none">
                    {/* Track surface (glow) */}
                    <path
                        d={svgPath}
                        stroke={isSelected ? "#22c55e" : "#52525b"}
                        strokeWidth="10"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                        opacity={isSelected ? 0.2 : 0.1}
                    />
                    {/* Track outline */}
                    <path
                        ref={pathRef}
                        d={svgPath}
                        stroke={isSelected ? "#22c55e" : "#71717a"}
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                    />
                    {/* Animated racing dot */}
                    <circle ref={dotRef} r="3.5" fill={isSelected ? "#22c55e" : "#a1a1aa"} />
                    {/* Glow */}
                    <circle r="6" fill={isSelected ? "#22c55e" : "#a1a1aa"} opacity="0.25">
                        <animate attributeName="r" values="5;8;5" dur="1.5s" repeatCount="indefinite" />
                        <animate attributeName="opacity" values="0.25;0.08;0.25" dur="1.5s" repeatCount="indefinite" />
                    </circle>
                </svg>
            </div>

            {/* Track info */}
            <div className="text-center mb-2">
                <div className="text-base font-bold text-white">{track.flag} {track.name}</div>
                <div className="text-[10px] text-zinc-500">{track.country} · {track.length}</div>
            </div>

            {/* Status badge */}
            <div className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all ${
                isSelected
                    ? "bg-green-500 text-white"
                    : "bg-green-500/15 text-green-400 border border-green-500/30"
            }`}>
                {isSelected ? "✓ Selected" : "Play Now"}
            </div>
        </button>
    );
};

/* ── Main Track Selection Screen ── */
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
            {/* Fullscreen button — matching reference style */}
            <button
                onClick={onFullscreen}
                className="absolute top-3 left-3 z-20 bg-white/90 hover:bg-white text-slate-700 px-3 py-1.5 rounded-full text-xs font-bold shadow-lg flex items-center gap-1.5 transition-all hover:scale-105"
            >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path>
                </svg>
                Fullscreen
            </button>

            {/* Back to Race Predictor */}
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
                {/* ── Welcome State ── */}
                {showWelcome && (
                    <div className="text-center animate-fadeIn">
                        <h1 className="text-3xl md:text-4xl font-bold mb-1">DrawLineRacing</h1>
                        <p className="text-zinc-400 text-lg mb-8">Welcome back! 👋</p>

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

                {/* ── Track Selection ── */}
                {!showWelcome && (
                    <div className="animate-fadeIn">
                        <div className="text-center mb-8">
                            <h1 className="text-3xl md:text-4xl font-bold mb-1">
                                Welcome back, <span className="text-green-400">{userName}</span>! 👋
                            </h1>
                            <p className="text-zinc-400 text-lg">Select Track</p>
                        </div>

                        {/* AI toggle */}
                        <div className="flex justify-center mb-6">
                            <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-full px-4 py-2">
                                <div className="w-2 h-2 rounded-full bg-green-400" />
                                <span className="text-xs text-zinc-400">AI Opponents ON</span>
                            </div>
                        </div>

                        {/* Track Grid */}
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

                        {/* Start Race Button */}
                        {selectedTrack && (
                            <div className="flex justify-center mt-8 animate-fadeIn">
                                <button
                                    onClick={handlePlay}
                                    className="flex items-center gap-3 bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-400 hover:to-emerald-400 text-white px-8 py-3 rounded-xl font-bold text-lg shadow-lg shadow-green-500/25 transition-all hover:scale-105 active:scale-95"
                                >
                                    🏁 Play Now
                                </button>
                            </div>
                        )}

                        {/* Change name link */}
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
