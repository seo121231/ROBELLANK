export const TIERS = [
  {
    key: "bronze",
    name: "브론즈",
    roleId: "1524024521999253514",
    rank: 0,
  },
  {
    key: "silver",
    name: "실버",
    roleId: "1524024634213929031",
    rank: 1,
  },
  {
    key: "gold",
    name: "골드",
    roleId: "1524024821808369765",
    rank: 2,
  },
  {
    key: "platinum",
    name: "플레티넘",
    roleId: "1524398392606855269",
    rank: 3,
  },
  {
    key: "ace",
    name: "에이스",
    roleId: "1524024941438304316",
    rank: 4,
  },
  {
    key: "vip",
    name: "VIP",
    roleId: "1524024999973884066",
    rank: 5,
  },
] as const;

export type TierKey = (typeof TIERS)[number]["key"];

export function getTier(key: string) {
  return TIERS.find((tier) => tier.key === key) ?? TIERS[0];
}

export function resolveTier(roleIds: Iterable<string>): (typeof TIERS)[number] {
  const roleSet = new Set(roleIds);
  return (
    [...TIERS].reverse().find((tier) => roleSet.has(tier.roleId)) ?? TIERS[0]
  );
}

export function tierAtLeast(tierKey: string, minimum: TierKey) {
  return getTier(tierKey).rank >= getTier(minimum).rank;
}

export function isLoanPriorityTier(tierKey: string) {
  return tierAtLeast(tierKey, "ace");
}
