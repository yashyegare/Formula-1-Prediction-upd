import React from 'react';

interface SponsorBannerProps {
  className?: string;
}

const SponsorBanner: React.FC<SponsorBannerProps> = ({ className = '' }) => {
  return (
    <a
      href="/racing"
      className={`group inline-flex items-center gap-1.5 h-8 px-3 bg-green-50 text-green-700 border border-green-200 font-medium rounded-md hover:bg-green-100 transition-colors text-sm ${className}`}
      aria-label="Try Draw Line Racing"
      title="Draw your own racing line!"
    >
      <span className="text-sm leading-none">🏁</span>
      <span>Draw Line Racing</span>
      <svg
        xmlns="http://www.w3.org/2000/svg"
        className="h-3 w-3 group-hover:translate-x-0.5 transition-transform"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
      </svg>
    </a>
  );
};

export default SponsorBanner;
