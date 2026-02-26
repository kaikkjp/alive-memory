"use client";

import { useEffect } from "react";

interface ToastNotificationProps {
  message: string;
  onDismiss: () => void;
  duration?: number;
}

export default function ToastNotification({
  message,
  onDismiss,
  duration = 5000,
}: ToastNotificationProps) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, duration);
    return () => clearTimeout(timer);
  }, [onDismiss, duration]);

  return (
    <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 animate-slide-up">
      <div className="px-4 py-2 bg-[#1a1a1a] border border-[#262620] rounded-full text-xs text-[#d4d4d4] shadow-lg">
        {message}
      </div>
    </div>
  );
}
