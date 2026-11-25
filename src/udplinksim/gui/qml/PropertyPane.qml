import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var theme
    required property var controller

    color: theme.bgSurface
    border.color: theme.border
    border.width: 1
    radius: 8
    clip: true

    property bool syncing: false
    property string currentRuleError: ""

    function loadSelected() {
        syncing = true
        let idx = controller.selectedIndex
        if (idx >= 0) {
            let r = controller.getRule(idx)
            fListenIp.text = r.listenIp || ""
            fListenPort.text = r.listenPort || ""
            fSourceIp.text = r.sourceIp || ""
            fSourcePort.text = r.sourcePort || ""
            fTargetIp.text = r.targetIp || ""
            fTargetPort.text = r.targetPort || ""
            fBaseMs.text = r.baseMs || "0"
            fSigmaMs.text = r.sigmaMs || "0"
            fLossPct.text = r.lossPct || "0"
            currentRuleError = r.errorText || ""
        } else {
            fListenIp.text = ""
            fListenPort.text = ""
            fSourceIp.text = ""
            fSourcePort.text = ""
            fTargetIp.text = ""
            fTargetPort.text = ""
            fBaseMs.text = ""
            fSigmaMs.text = ""
            fLossPct.text = ""
            currentRuleError = ""
        }
        syncing = false
    }

    function commitEdit() {
        if (syncing || controller.selectedIndex < 0) return
        controller.updateRule(
            controller.selectedIndex,
            fListenIp.text, fListenPort.text,
            fSourceIp.text, fSourcePort.text,
            fTargetIp.text, fTargetPort.text,
            fBaseMs.text, fSigmaMs.text, fLossPct.text
        )
        let r = controller.getRule(controller.selectedIndex)
        currentRuleError = r.errorText || ""
    }

    Connections {
        target: controller
        function onSelectedIndexChanged() { root.loadSelected() }
        function onConfigPathChanged() { root.loadSelected() }
        function onValidationChanged() {
            if (controller.selectedIndex >= 0) {
                let r = controller.getRule(controller.selectedIndex)
                root.currentRuleError = r.errorText || ""
            }
        }
    }

    Component.onCompleted: loadSelected()

    component FieldInput: TextField {
        Layout.fillWidth: true
        implicitHeight: 32
        font.pixelSize: 12
        font.family: "Consolas"
        color: theme.textPrimary
        selectionColor: theme.accent
        selectedTextColor: "#FFFFFF"
        placeholderTextColor: theme.textMuted
        leftPadding: 8
        rightPadding: 8
        background: Rectangle {
            radius: 5
            color: parent.enabled ? theme.bgSubtle : theme.bgApp
            border.color: parent.activeFocus ? theme.accent : theme.border
            border.width: parent.activeFocus ? 1.5 : 1
        }
        onTextEdited: root.commitEdit()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            height: 36
            color: theme.bgHeader
            border.color: theme.borderSubtle
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                Text {
                    text: controller.selectedIndex >= 0
                          ? "规则属性 — 第 " + (controller.selectedIndex + 1) + " 条"
                          : "规则属性"
                    font.pixelSize: 13
                    font.bold: true
                    color: theme.textPrimary
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: parent.width
                spacing: 10

                // Error banner
                Rectangle {
                    Layout.fillWidth: true
                    Layout.margins: 12
                    Layout.bottomMargin: 0
                    visible: root.currentRuleError !== ""
                    color: theme.dangerBg
                    border.color: theme.danger
                    border.width: 1
                    radius: 6
                    implicitHeight: errTxt.implicitHeight + 14

                    Text {
                        id: errTxt
                        anchors.fill: parent
                        anchors.margins: 7
                        text: root.currentRuleError
                        color: theme.danger
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }
                }

                // Pending notice
                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 12
                    Layout.rightMargin: 12
                    Layout.topMargin: root.currentRuleError === "" ? 12 : 0
                    visible: controller.hasPendingApply
                    color: theme.warningBg
                    border.color: theme.warning
                    border.width: 1
                    radius: 6
                    implicitHeight: pendTxt.implicitHeight + 12

                    Text {
                        id: pendTxt
                        anchors.fill: parent
                        anchors.margins: 6
                        text: "配置已修改但尚未应用，请点击顶部「应用并重启」生效。"
                        color: theme.warning
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    Layout.margins: 12
                    columns: 2
                    columnSpacing: 8
                    rowSpacing: 8
                    enabled: controller.selectedIndex >= 0

                    Text { text: "监听 IP"; font.pixelSize: 11; color: theme.textSecondary }
                    Text { text: "监听端口 (1-65535)"; font.pixelSize: 11; color: theme.textSecondary }
                    FieldInput { id: fListenIp; placeholderText: "127.0.0.1" }
                    FieldInput { id: fListenPort; placeholderText: "20001" }

                    Text { text: "来源 IP"; font.pixelSize: 11; color: theme.textSecondary }
                    Text { text: "来源端口 (0=通配)"; font.pixelSize: 11; color: theme.textSecondary }
                    FieldInput { id: fSourceIp; placeholderText: "127.0.0.1" }
                    FieldInput { id: fSourcePort; placeholderText: "0 或具体端口" }

                    Text { text: "目标 IP"; font.pixelSize: 11; color: theme.textSecondary }
                    Text { text: "目标端口 (1-65535)"; font.pixelSize: 11; color: theme.textSecondary }
                    FieldInput { id: fTargetIp; placeholderText: "127.0.0.1" }
                    FieldInput { id: fTargetPort; placeholderText: "22001" }

                    Text { text: "基准延迟 base_ms"; font.pixelSize: 11; color: theme.textSecondary }
                    Text { text: "高斯抖动 sigma_ms"; font.pixelSize: 11; color: theme.textSecondary }
                    FieldInput { id: fBaseMs; placeholderText: "20" }
                    FieldInput { id: fSigmaMs; placeholderText: "0" }

                    Text {
                        text: "独立丢包率 loss_pct (0~100%)"
                        font.pixelSize: 11
                        color: theme.textSecondary
                        Layout.columnSpan: 2
                    }
                    FieldInput {
                        id: fLossPct
                        placeholderText: "0"
                        Layout.columnSpan: 2
                    }
                }

                // Helpful semantics hint
                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 12
                    Layout.rightMargin: 12
                    color: theme.bgSubtle
                    border.color: theme.borderSubtle
                    border.width: 1
                    radius: 6
                    implicitHeight: hintTxt.implicitHeight + 14

                    Text {
                        id: hintTxt
                        anchors.fill: parent
                        anchors.margins: 7
                        font.pixelSize: 11
                        color: theme.textSecondary
                        wrapMode: Text.WordWrap
                        text: "• 匹配顺序：先精确匹配 (IP, 端口)，再匹配同 IP 端口 0 通配。\n"
                            + "• 转发目标固定，不随对端临时源端口漂移。\n"
                            + "• 先执行独立伯努利丢包，再采样非负截断高斯延迟（允许乱序）。"
                    }
                }

                // Row actions
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 12
                    spacing: 8
                    enabled: controller.selectedIndex >= 0

                    Button {
                        Layout.fillWidth: true
                        text: "复制此规则"
                        onClicked: controller.duplicateRule(controller.selectedIndex)
                        contentItem: Text {
                            text: parent.text
                            font.pixelSize: 12
                            color: theme.textPrimary
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 6
                            color: parent.hovered ? theme.bgHover : theme.bgSubtle
                            border.color: theme.border
                        }
                    }

                    Button {
                        Layout.fillWidth: true
                        text: "删除此规则"
                        onClicked: controller.deleteRule(controller.selectedIndex)
                        contentItem: Text {
                            text: parent.text
                            font.pixelSize: 12
                            color: theme.danger
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 6
                            color: parent.hovered ? theme.dangerBg : theme.bgSubtle
                            border.color: theme.danger
                        }
                    }
                }
            }
        }
    }
}
