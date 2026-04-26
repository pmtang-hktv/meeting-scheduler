from datetime import date

# Hong Kong public holidays 2024–2027
HK_HOLIDAYS: frozenset[date] = frozenset([
    # 2024
    date(2024, 1, 1),   # New Year's Day
    date(2024, 2, 10),  # Lunar New Year
    date(2024, 2, 12),  # Lunar New Year
    date(2024, 2, 13),  # Lunar New Year
    date(2024, 3, 29),  # Good Friday
    date(2024, 4, 1),   # Easter Monday
    date(2024, 4, 4),   # Ching Ming Festival
    date(2024, 5, 1),   # Labour Day
    date(2024, 5, 15),  # Buddha's Birthday
    date(2024, 6, 10),  # Tuen Ng Festival
    date(2024, 7, 1),   # HKSAR Establishment Day
    date(2024, 9, 18),  # Day after Mid-Autumn Festival
    date(2024, 10, 1),  # National Day
    date(2024, 10, 11), # Chung Yeung Festival
    date(2024, 12, 25), # Christmas Day
    date(2024, 12, 26), # Boxing Day
    # 2025
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 29),  # Lunar New Year
    date(2025, 1, 30),  # Lunar New Year
    date(2025, 1, 31),  # Lunar New Year
    date(2025, 4, 4),   # Ching Ming Festival
    date(2025, 4, 18),  # Good Friday
    date(2025, 4, 21),  # Easter Monday
    date(2025, 5, 1),   # Labour Day
    date(2025, 5, 5),   # Buddha's Birthday
    date(2025, 5, 31),  # Tuen Ng Festival
    date(2025, 7, 1),   # HKSAR Establishment Day
    date(2025, 10, 1),  # National Day
    date(2025, 10, 7),  # Day after Mid-Autumn Festival
    date(2025, 10, 29), # Chung Yeung Festival
    date(2025, 12, 25), # Christmas Day
    date(2025, 12, 26), # Boxing Day
    # 2026
    date(2026, 1, 1),   # New Year's Day
    date(2026, 2, 17),  # Lunar New Year
    date(2026, 2, 18),  # Lunar New Year
    date(2026, 2, 19),  # Lunar New Year
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 5),   # Ching Ming Festival (observance day)
    date(2026, 4, 6),   # Easter Monday
    date(2026, 5, 1),   # Labour Day
    date(2026, 5, 25),  # Buddha's Birthday
    date(2026, 6, 19),  # Tuen Ng Festival
    date(2026, 7, 1),   # HKSAR Establishment Day
    date(2026, 9, 25),  # Day after Mid-Autumn Festival
    date(2026, 10, 1),  # National Day
    date(2026, 10, 19), # Chung Yeung Festival
    date(2026, 12, 25), # Christmas Day
    date(2026, 12, 26), # Boxing Day (observed on Monday)
    # 2027
    date(2027, 1, 1),   # New Year's Day
    date(2027, 2, 6),   # Lunar New Year
    date(2027, 2, 8),   # Lunar New Year
    date(2027, 2, 9),   # Lunar New Year
    date(2027, 3, 26),  # Good Friday
    date(2027, 3, 29),  # Easter Monday
    date(2027, 4, 5),   # Ching Ming Festival
    date(2027, 5, 1),   # Labour Day
    date(2027, 5, 13),  # Buddha's Birthday
    date(2027, 6, 9),   # Tuen Ng Festival
    date(2027, 7, 1),   # HKSAR Establishment Day
    date(2027, 9, 16),  # Day after Mid-Autumn Festival
    date(2027, 10, 1),  # National Day
    date(2027, 10, 8),  # Chung Yeung Festival
    date(2027, 12, 25), # Christmas Day
    date(2027, 12, 27), # Boxing Day (observed)
])
