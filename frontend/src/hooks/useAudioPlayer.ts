/**
 * 1 本の音声を、文単位で制御する。
 *
 * 画面からは play / pause / back / replaySentence / nextSentence だけを呼ぶ。
 * 再生位置は画面の描画ごと（requestAnimationFrame）に読み取る。ブラウザが
 * timeupdate で知らせる位置は 0.25 秒おきと粗く、句点区切りで止める位置を
 * 行き過ぎることがあるため。
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { isAtSentenceEnd, rewindMs, sentenceIndexAt, sentenceStopMs, type SentenceMark } from "../lib/playback";

export type PlaybackMode = "through" | "sentence";

type Options = {
  src: string;
  sentences: readonly SentenceMark[];
  /** API が返す音声の長さ。音声の読み込み前から進行バーを描くために使う */
  durationMs?: number | null;
  /** 音声を読み込めなかったとき（署名付き URL の期限切れなど）に呼ぶ */
  onError?: () => void;
};

export function useAudioPlayer({ src, sentences, durationMs: durationHint, onError }: Options) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });
  const stopAtRef = useRef<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [currentMs, setCurrentMs] = useState(0);
  const [durationMs, setDurationMs] = useState(durationHint ?? 0);
  const [started, setStarted] = useState(false);
  const [mode, setModeState] = useState<PlaybackMode>("through");
  const [rate, setRateState] = useState(1);

  // 音声の要素は画面に置かず、ここで 1 つだけ作る
  useEffect(() => {
    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;
    const onEnded = () => setPlaying(false);
    const onPause = () => setPlaying(false);
    const onPlay = () => setPlaying(true);
    const onMetadata = () => {
      if (Number.isFinite(audio.duration)) setDurationMs(audio.duration * 1000);
    };
    const onLoadError = () => onErrorRef.current?.();
    audio.addEventListener("error", onLoadError);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("loadedmetadata", onMetadata);
    return () => {
      audio.pause();
      audio.removeEventListener("error", onLoadError);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("loadedmetadata", onMetadata);
      audioRef.current = null;
    };
  }, []);

  // URL が変わったら差し替える。署名付き URL の期限切れで取り直したときも、
  // 聞いていた位置から続けられるよう再生位置を引き継ぐ
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || audio.src === src) return;
    const position = audio.currentTime;
    const wasPlaying = !audio.paused;
    audio.src = src;
    audio.playbackRate = rate;
    if (position > 0) {
      audio.addEventListener(
        "loadedmetadata",
        () => {
          audio.currentTime = position;
          if (wasPlaying) void audio.play();
        },
        { once: true },
      );
    }
    // rate は変わっても src を差し替える理由にならないので、依存に含めない
  }, [src]);

  // 再生中は描画ごとに位置を読み、句点区切りなら止める位置で止める
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const audio = audioRef.current;
      if (!audio) return;
      const ms = audio.currentTime * 1000;
      const stopAt = stopAtRef.current;
      if (stopAt !== null && ms >= stopAt) {
        audio.pause();
        audio.currentTime = stopAt / 1000;
        stopAtRef.current = null;
        setCurrentMs(stopAt);
        return;
      }
      setCurrentMs(ms);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  const seek = useCallback((ms: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = ms / 1000;
    setCurrentMs(ms);
  }, []);

  const startFrom = useCallback(
    async (ms: number) => {
      const audio = audioRef.current;
      if (!audio) return;
      seek(ms);
      // 句点区切りなら、今の文の終わりで止まるよう予約する
      stopAtRef.current = mode === "sentence" ? sentenceStopMs(sentences, sentenceIndexAt(sentences, ms)) : null;
      setStarted(true);
      await audio.play();
    },
    [mode, seek, sentences],
  );

  const play = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio) return;
    const ms = audio.currentTime * 1000;
    if (audio.ended) return startFrom(0);
    // 句点区切りで文の終わりに止まっているなら、次の文から始める
    if (mode === "sentence" && isAtSentenceEnd(sentences, ms)) {
      const next = sentences[sentenceIndexAt(sentences, ms) + 1];
      if (next) return startFrom(next.start_ms);
    }
    return startFrom(ms);
  }, [mode, sentences, startFrom]);

  const pause = useCallback(() => {
    stopAtRef.current = null;
    audioRef.current?.pause();
  }, []);

  const toggle = useCallback(() => (playing ? pause() : void play()), [pause, play, playing]);

  /** 通し再生: n 秒戻して続ける。 */
  const back = useCallback(
    (seconds: number) => {
      const target = rewindMs(currentMs, seconds);
      if (playing) void startFrom(target);
      else seek(target);
    },
    [currentMs, playing, seek, startFrom],
  );

  /** 句点区切り: 今の文を頭からもう一度。 */
  const replaySentence = useCallback(() => {
    // 文の終わりで止まっている位置も、止める位置が次の文の開始より手前なので、今の文と判定される
    const index = sentenceIndexAt(sentences, currentMs);
    void startFrom(sentences[index]?.start_ms ?? 0);
  }, [currentMs, sentences, startFrom]);

  /** 句点区切り: 次の文へ。最後の文なら何もしない。 */
  const nextSentence = useCallback(() => {
    const next = sentences[sentenceIndexAt(sentences, currentMs) + 1];
    if (next) void startFrom(next.start_ms);
  }, [currentMs, sentences, startFrom]);

  const setMode = useCallback((next: PlaybackMode) => {
    setModeState(next);
    // 切り替えたら止める予約を解く（次に再生するときに改めて決まる）
    stopAtRef.current = null;
  }, []);

  const setRate = useCallback((next: number) => {
    setRateState(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
  }, []);

  /** 同じ問題にもう一度: 先頭に戻して止める。 */
  const reset = useCallback(() => {
    pause();
    seek(0);
    setStarted(false);
  }, [pause, seek]);

  return {
    playing,
    started,
    currentMs,
    durationMs,
    currentIndex: sentenceIndexAt(sentences, currentMs),
    mode,
    rate,
    toggle,
    back,
    replaySentence,
    nextSentence,
    setMode,
    setRate,
    reset,
    pause,
  };
}
