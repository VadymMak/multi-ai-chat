import React from "react";

const LoadingOverlay: React.FC = () => {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-white/80 backdrop-blur-sm">
      <div className="text-center text-gray-600 animate-pulse">
        <div className="text-lg font-semibold">Loading your chat...</div>
        <div className="mt-2 text-sm">Please wait</div>
      </div>
    </div>
  );
};

export default LoadingOverlay;
