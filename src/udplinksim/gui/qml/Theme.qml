import QtQuick

QtObject {
    id: theme
    property bool dark: false

    readonly property color bgApp: dark ? "#0B1120" : "#F1F5F9"
    readonly property color bgSurface: dark ? "#111827" : "#FFFFFF"
    readonly property color bgSubtle: dark ? "#1E293B" : "#F8FAFC"
    readonly property color bgHover: dark ? "#273549" : "#EFF6FF"
    readonly property color bgSelected: dark ? "#1D3A5F" : "#DBEAFE"
    readonly property color bgHeader: dark ? "#162033" : "#F8FAFC"

    readonly property color border: dark ? "#2D3B52" : "#CBD5E1"
    readonly property color borderSubtle: dark ? "#1E293B" : "#E2E8F0"

    readonly property color textPrimary: dark ? "#F1F5F9" : "#0F172A"
    readonly property color textSecondary: dark ? "#94A3B8" : "#475569"
    readonly property color textMuted: dark ? "#64748B" : "#64748B"

    readonly property color accent: dark ? "#3B82F6" : "#2563EB"
    readonly property color accentHover: dark ? "#60A5FA" : "#1D4ED8"
    readonly property color accentText: "#FFFFFF"

    readonly property color success: dark ? "#22C55E" : "#16A34A"
    readonly property color successBg: dark ? "#143523" : "#DCFCE7"
    readonly property color warning: dark ? "#F59E0B" : "#D97706"
    readonly property color warningBg: dark ? "#3A280A" : "#FEF3C7"
    readonly property color danger: dark ? "#EF4444" : "#DC2626"
    readonly property color dangerBg: dark ? "#3F1518" : "#FEE2E2"
}
