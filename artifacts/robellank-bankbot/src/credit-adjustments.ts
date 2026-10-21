export const CREDIT_ADJUSTMENTS = [
  { key: "savings_maturity", label: "적금 만기 유지 (+2점)", delta: 2 },
  { key: "savings_early", label: "적금 중도 해지 (-1점)", delta: -1 },
  { key: "collateral_on_time", label: "담보대출 기한 내 상환 (+3점)", delta: 3 },
  { key: "collateral_early", label: "담보대출 조기 상환 추가 (+1점)", delta: 1 },
  { key: "collateral_overdue", label: "담보대출 연체 (-5점)", delta: -5 },
  { key: "credit_on_time", label: "신용대출 기한 내 상환 (+3점)", delta: 3 },
  { key: "credit_early", label: "신용대출 조기 상환 추가 (+1점)", delta: 1 },
  { key: "credit_overdue", label: "신용대출 연체 (-5점)", delta: -5 },
  { key: "long_overdue", label: "장기 연체 (-10점)", delta: -10 },
  { key: "rule_violation", label: "은행 규칙 위반 (-3점)", delta: -3 },
  { key: "false_application", label: "허위 신청·인증 (-10점)", delta: -10 },
  { key: "rule_abuse", label: "규칙 악용 (-5점)", delta: -5 },
  { key: "fraud", label: "사기·기만 행위 (-25점)", delta: -25 },
  {
    key: "punishment_evasion",
    label: "처벌 회피 시도 (-15점 · 타임아웃 별도)",
    delta: -15,
  },
  { key: "bank_damage", label: "은행 운영 피해 (-15점)", delta: -15 },
  { key: "bank_staff", label: "은행 직원 선임 (+10점)", delta: 10 },
] as const;

export type CreditAdjustmentKey = (typeof CREDIT_ADJUSTMENTS)[number]["key"];

export function getCreditAdjustment(key: string) {
  return CREDIT_ADJUSTMENTS.find((adjustment) => adjustment.key === key);
}
