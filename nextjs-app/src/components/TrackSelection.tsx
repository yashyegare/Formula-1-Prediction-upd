import React, { useEffect, useRef, useState } from "react";

/* ── Track SVG outlines (simplified but recognizable) ── */
const TRACK_SVGS: Record<string, { path: string; viewBox: string; flag: string; country: string; length: string }> = {
    Monaco: {
        viewBox: "0 0 200 160",
        flag: "🇲🇨",
        country: "Monaco",
        length: "3.337 km",
        // Tight harbor loop: Ste Devote up, hairpin center, tunnel east, swimming pool right
        path: "M100,145 L85,130 L75,110 L70,90 L68,75 L72,60 L80,48 L92,40 L105,38 L118,42 L128,50 L132,62 L130,75 L122,85 L110,90 L100,92 L92,88 L88,80 L90,70 L96,62 L105,58 L112,62 L115,70 L112,78 L105,82 L100,85 L118,90 L128,95 L135,105 L132,118 L122,130 L110,140 L100,145 Z",
    },
    Silverstone: {
        viewBox: "0 0 220 160",
        flag: "🇬🇧",
        country: "United Kingdom",
        length: "5.891 km",
        // Rounded triangle: Copse top-right, Maggotts-Becketts right, Stowe bottom-right, Club bottom, Abbey left
        path: "M80,30 L110,25 L140,28 L165,38 L180,55 L185,75 L178,95 L165,110 L145,125 L120,135 L95,138 L70,132 L50,120 L38,105 L32,85 L35,65 L45,48 L58,36 L80,30 Z",
    },
    Suzuka: {
        viewBox: "0 0 200 180",
        flag: "🇯🇵",
        country: "Japan",
        length: "5.807 km",
        // Figure-8: S-curves left, hairpin bottom, Spoon right, crossover center, 130R top
        path: "M60,30 L80,40 L95,55 L85,70 L70,75 L60,68 L55,55 L60,42 L75,38 L90,45 L100,58 L105,75 L100,90 L88,100 L75,108 L65,118 L60,132 L65,145 L80,152 L100,150 L118,142 L130,130 L135,115 L130,100 L118,92 L108,88 L115,78 L125,70 L140,65 L155,68 L165,78 L168,92 L162,105 L150,112 L138,108 L130,100 L135,88 L145,80 L155,78 L162,85 L160,95 L152,102 L142,100 L135,92 L130,85 L125,75 L118,65 L110,55 L100,48 L88,42 L75,38 L65,35 L60,30 Z",
    },
    Spa: {
        viewBox: "0 0 140 220",
        flag: "🇧🇪",
        country: "Belgium",
        length: "7.004 km",
        // Long narrow N-S: La Source top, Eau Rouge compression, Kemmel straight, Les Combes, Pouhon, Bus Stop
        path: "M50,20 L65,18 L75,25 L78,38 L75,50 L68,58 L60,62 L55,70 L52,82 L48,95 L42,108 L38,122 L40,135 L48,145 L58,150 L68,148 L78,142 L85,132 L88,120 L85,108 L78,100 L68,95 L58,92 L50,88 L45,80 L42,70 L45,58 L52,50 L60,45 L68,42 L75,45 L78,55 L75,65 L68,72 L58,75 L50,72 L45,65 L42,55 L45,45 L52,38 L60,35 L68,38 L72,45 L70,55 L62,60 L55,58 L50,50 L48,40 L52,30 L58,25 L65,22 L72,25 L78,32 L82,42 L80,55 L72,62 L62,65 L55,62 L50,55 L48,45 L52,38 L60,35 L68,38 Z",
    },
    Interlagos: {
        viewBox: "0 0 200 160",
        flag: "🇧🇷",
        country: "Brazil",
        length: "4.309 km",
        // Counter-clockwise: Senna S downhill, Ferradura, Bico de Pato, Junção, uphill back straight
        path: "M155,45 L140,50 L125,58 L112,68 L105,80 L100,92 L95,105 L85,115 L72,120 L58,118 L48,110 L42,98 L40,85 L44,72 L52,62 L62,55 L75,50 L88,48 L100,50 L112,55 L122,62 L128,72 L125,82 L118,88 L108,90 L98,88 L90,82 L85,72 L85,62 L90,52 L100,48 L112,46 L125,48 L138,52 L148,58 L155,45 Z",
    },
};

/* ── Animated SVG Track Preview ── */
interface TrackData {
    path: string;
    viewBox: string;
    flag: string;
    country: string;
    length: string;
}

const TrackPreview = ({ trackName, track, isSelected, onClick }: {
    trackName: string;
    track: TrackData;
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

            // Speed: traverse the full path in ~3 seconds
            progressRef.current = (progressRef.current + delta / 3000) % 1;
            const point = path.getPointAtLength(progressRef.current * totalLength);
            dot.setAttribute("cx", String(point.x));
            dot.setAttribute("cy", String(point.y));

            animRef.current = requestAnimationFrame(animate);
        };

        animRef.current = requestAnimationFrame(animate);
        return () => cancelAnimationFrame(animRef.current);
    }, []);

    return (
        <button
            onClick={onClick}
            className={`group relative flex flex-col items-center gap-3 rounded-2xl border-2 p-5 transition-all duration-300 cursor-pointer ${
                isSelected
                    ? "border-red-500 bg-red-500/10 shadow-lg shadow-red-500/20 scale-[1.02]"
                    : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-600 hover:bg-zinc-900"
            }`}
        >
            {/* Track SVG */}
            <div className="relative w-full aspect-[4/3] flex items-center justify-center">
                <svg
                    viewBox={track.viewBox}
                    className="w-full h-full"
                    fill="none"
                >
                    {/* Track surface */}
                    <path
                        d={track.path}
                        stroke={isSelected ? "#ef4444" : "#52525b"}
                        strokeWidth="8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                        opacity={isSelected ? 0.3 : 0.15}
                    />
                    {/* Track outline */}
                    <path
                        ref={pathRef}
                        d={track.path}
                        stroke={isSelected ? "#ef4444" : "#71717a"}
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                        className="transition-all duration-300"
                    />
                    {/* Animated racing dot */}
                    <circle
                        ref={dotRef}
                        r="4"
                        fill={isSelected ? "#ef4444" : "#a1a1aa"}
                        className="transition-all duration-300"
                    />
                    {/* Glow effect on dot */}
                    <circle
                        r="8"
                        fill={isSelected ? "#ef4444" : "#a1a1aa"}
                        opacity="0.3"
                        className="animate-pulse"
                    >
                        <animate attributeName="r" values="6;10;6" dur="1.5s" repeatCount="indefinite" />
                        <animate attributeName="opacity" values="0.3;0.1;0.3" dur="1.5s" repeatCount="indefinite" />
                    </circle>
                </svg>
            </div>

            {/* Track info */}
            <div className="text-center">
                <div className="text-lg font-bold text-white">{track.flag} {trackName}</div>
                <div className="text-xs text-zinc-500 mt-0.5">{track.country} · {track.length}</div>
            </div>

            {/* Play indicator */}
            <div className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-bold transition-all ${
                isSelected
                    ? "bg-red-500 text-white"
                    : "bg-zinc-800 text-zinc-400 group-hover:bg-zinc-700 group-hover:text-white"
            }`}>
                {isSelected ? (
                    <>
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M8 5v14l11-7z"/>
                        </svg>
                        Play Now
                    </>
                ) : (
                    "Select"
                )}
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

    useEffect(() => {
        const stored = localStorage.getItem("dlr_username");
        if (stored) setUserName(stored);
    }, []);

    const handlePlay = () => {
        if (selectedTrack) {
            // Save username for next visit
            localStorage.setItem("dlr_username", userName);
            onSelectTrack(selectedTrack);
        }
    };

    return (
        <div className="min-h-screen bg-[#0a0d16] text-white">
            {/* Fullscreen button */}
            <button
                onClick={onFullscreen}
                className="absolute top-4 right-4 z-30 bg-white/90 hover:bg-white text-slate-700 w-10 h-10 rounded-full shadow-lg flex items-center justify-center transition-all hover:scale-110"
                title="Toggle Fullscreen"
            >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                    <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path>
                </svg>
            </button>

            <div className="max-w-6xl mx-auto px-4 py-8">
                {/* Welcome Header */}
                {showWelcome && (
                    <div className="text-center mb-10 animate-fadeIn">
                        <div className="inline-flex items-center gap-2 bg-red-500/10 border border-red-500/20 rounded-full px-4 py-1.5 mb-4">
                            <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                            <span className="text-xs font-semibold text-red-400 uppercase tracking-wider">Draw Line Racing</span>
                        </div>

                        <h1 className="text-4xl md:text-5xl font-bold mb-2">
                            Welcome back, <span className="text-red-500">{userName}</span>! 👋
                        </h1>
                        <p className="text-lg text-zinc-400 mb-6">Select a track to start racing</p>

                        {/* Username input */}
                        <div className="flex items-center justify-center gap-3 mb-2">
                            <input
                                type="text"
                                value={userName}
                                onChange={(e) => setUserName(e.target.value)}
                                placeholder="Enter your name"
                                className="bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-white text-sm outline-none focus:border-red-500 transition-colors w-48"
                            />
                            <button
                                onClick={() => setShowWelcome(false)}
                                className="bg-zinc-800 hover:bg-zinc-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                            >
                                Confirm
                            </button>
                        </div>
                    </div>
                )}

                {/* Collapsed header when name is confirmed */}
                {!showWelcome && (
                    <div className="flex items-center justify-between mb-8 animate-fadeIn">
                        <div>
                            <h1 className="text-2xl font-bold">
                                Hey <span className="text-red-500">{userName}</span>, pick a track
                            </h1>
                            <p className="text-sm text-zinc-500">Draw your racing line and compete</p>
                        </div>
                        <button
                            onClick={() => setShowWelcome(true)}
                            className="text-xs text-zinc-500 hover:text-white transition-colors bg-zinc-900 px-3 py-1.5 rounded-lg"
                        >
                            Change Name
                        </button>
                    </div>
                )}

                {/* Track Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                    {Object.entries(TRACK_SVGS).map(([name, track]) => (
                        <TrackPreview
                            key={name}
                            trackName={name}
                            track={track!}
                            isSelected={selectedTrack === name}
                            onClick={() => setSelectedTrack(name)}
                        />
                    ))}
                </div>

                {/* Start Race Button */}
                {selectedTrack && (
                    <div className="flex justify-center mt-8 animate-fadeIn">
                        <button
                            onClick={handlePlay}
                            className="flex items-center gap-3 bg-gradient-to-r from-red-600 to-red-500 hover:from-red-500 hover:to-red-400 text-white px-8 py-4 rounded-xl font-bold text-lg shadow-lg shadow-red-500/25 transition-all hover:scale-105 active:scale-95"
                        >
                            <span className="text-2xl">🏁</span>
                            Start Racing — {selectedTrack}
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                            </svg>
                        </button>
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
