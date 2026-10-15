import { createContext, useContext, useEffect, useState } from "react";
import { CARD_TYPE, type CardType } from "../theme";

/**
 * 总览卡片的字号/尺寸标尺。App 在总览外面按窗口尺寸提供它，卡片组件只管读。
 * 缺省（没有 Provider，例如别的页面/测试里单独渲染卡片）= 常规档，行为与以前一致。
 */
export const CardTypeContext = createContext<CardType>(CARD_TYPE);

export function useCardType(): CardType {
  return useContext(CardTypeContext);
}

/** 小窗口判据：宽度与侧栏自动收起的 `NARROW_W` 同一条线，或高度矮到卡片区只露出不到两排。 */
export const COMPACT_W = 960;
export const COMPACT_H = 640;

export function useCompactCards(): boolean {
  const calc = () => window.innerWidth < COMPACT_W || window.innerHeight < COMPACT_H;
  const [compact, setCompact] = useState(calc);
  useEffect(() => {
    const on = () => setCompact(calc());
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return compact;
}

