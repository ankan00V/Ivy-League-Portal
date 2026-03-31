export {};

declare global {
  interface PuterChatPart {
    text?: string;
  }

  interface PuterChatResponse {
    message?: {
      content?: Array<{
        text?: string;
      }>;
    };
  }

  interface PuterAI {
    chat: (
      prompt: string,
      options?: {
        model?: string;
        stream?: boolean;
      }
    ) => Promise<PuterChatResponse | AsyncIterable<PuterChatPart>>;
  }

  interface PuterGlobal {
    ai?: PuterAI;
    print?: (...args: unknown[]) => void;
  }

  interface Window {
    puter?: PuterGlobal;
  }
}
