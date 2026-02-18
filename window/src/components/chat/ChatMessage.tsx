'use client';

import type { ChatMessage as ChatMessageData } from '@/lib/types';

interface ChatMessageProps {
  message: ChatMessageData;
}

/**
 * Individual chat message — visitor messages right-aligned, shopkeeper left-aligned.
 */
export default function ChatMessageItem({ message }: ChatMessageProps) {
  return (
    <div className={`chat-message chat-message--${message.sender}`}>
      {message.content}
    </div>
  );
}
