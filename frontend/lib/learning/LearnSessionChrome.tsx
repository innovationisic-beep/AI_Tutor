"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { PlanProgressionView } from "@/lib/types";

type LearnSessionChromeState = {
  clusterLabel: string | null;
  conceptLabel: string | null;
  topicTitle: string | null;
  planProgression: PlanProgressionView | null;
  setClusterLabel: (label: string | null) => void;
  setConceptLabel: (label: string | null) => void;
  setTopicTitle: (title: string | null) => void;
  setPlanProgression: (progression: PlanProgressionView | null) => void;
};

const LearnSessionChromeContext = createContext<LearnSessionChromeState | null>(
  null
);

export function LearnSessionChromeProvider({ children }: { children: ReactNode }) {
  const [clusterLabel, setClusterLabelState] = useState<string | null>(null);
  const [conceptLabel, setConceptLabelState] = useState<string | null>(null);
  const [topicTitle, setTopicTitleState] = useState<string | null>(null);
  const [planProgression, setPlanProgressionState] =
    useState<PlanProgressionView | null>(null);

  const setClusterLabel = useCallback((label: string | null) => {
    setClusterLabelState(label);
  }, []);

  const setConceptLabel = useCallback((label: string | null) => {
    setConceptLabelState(label);
  }, []);

  const setTopicTitle = useCallback((title: string | null) => {
    setTopicTitleState(title);
  }, []);

  const setPlanProgression = useCallback((progression: PlanProgressionView | null) => {
    setPlanProgressionState(progression);
  }, []);

  const value = useMemo(
    () => ({
      clusterLabel,
      conceptLabel,
      topicTitle,
      planProgression,
      setClusterLabel,
      setConceptLabel,
      setTopicTitle,
      setPlanProgression,
    }),
    [
      clusterLabel,
      conceptLabel,
      topicTitle,
      planProgression,
      setClusterLabel,
      setConceptLabel,
      setTopicTitle,
      setPlanProgression,
    ]
  );

  return (
    <LearnSessionChromeContext.Provider value={value}>
      {children}
    </LearnSessionChromeContext.Provider>
  );
}

export function useLearnSessionChrome(): LearnSessionChromeState | null {
  return useContext(LearnSessionChromeContext);
}
