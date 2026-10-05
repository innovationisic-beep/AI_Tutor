"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type RecognitionInstance = {
  lang: string;
  interimResults: boolean;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onresult: ((event: { results: { [key: number]: { [key: number]: { transcript: string } } } }) => void) | null;
  start: () => void;
  stop: () => void;
};

export function useSpeechToText() {
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<RecognitionInstance | null>(null);

  const stopListening = useCallback(() => {
    try {
      recognitionRef.current?.stop();
    } catch {
      /* ignore */
    }
    recognitionRef.current = null;
    setIsListening(false);
  }, []);

  const startListening = useCallback(
    (onResult: (text: string) => void) => {
      if (typeof window === "undefined") return;

      const SpeechRecognitionCtor =
        (
          window as unknown as {
            SpeechRecognition?: new () => RecognitionInstance;
            webkitSpeechRecognition?: new () => RecognitionInstance;
          }
        ).SpeechRecognition ||
        (
          window as unknown as {
            webkitSpeechRecognition?: new () => RecognitionInstance;
          }
        ).webkitSpeechRecognition;

      if (!SpeechRecognitionCtor) {
        window.alert("Speech recognition is not supported in this browser.");
        return;
      }

      stopListening();

      const recognition = new SpeechRecognitionCtor();
      recognition.lang = "en-US";
      recognition.interimResults = false;

      recognition.onstart = () => setIsListening(true);
      recognition.onend = () => {
        setIsListening(false);
        recognitionRef.current = null;
      };

      recognition.onresult = (event: {
        results: { [key: number]: { [key: number]: { transcript: string } } };
      }) => {
        const text = event.results[0]?.[0]?.transcript;
        if (text != null && String(text).trim()) {
          onResult(String(text).trim());
        }
      };

      try {
        recognition.start();
        recognitionRef.current = recognition;
      } catch {
        setIsListening(false);
        recognitionRef.current = null;
      }
    },
    [stopListening]
  );

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop();
      } catch {
        /* ignore */
      }
      recognitionRef.current = null;
    };
  }, []);

  return { isListening, startListening, stopListening };
}
