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

    property int activeTab: 0

    component StatChip: Rectangle {
        property string label: ""
        property string value: ""
        property color valueColor: theme.textPrimary
        radius: 5
        color: theme.bgSubtle
        border.color: theme.borderSubtle
        implicitHeight: 28
        implicitWidth: chipRow.implicitWidth + 14

        Row {
            id: chipRow
            anchors.centerIn: parent
            spacing: 5
            Text { text: label; font.pixelSize: 11; color: theme.textSecondary }
            Text { text: value; font.pixelSize: 11; font.bold: true; font.family: "Consolas"; color: valueColor }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Diagnostics top summary bar
        Rectangle {
            Layout.fillWidth: true
            height: 40
            color: theme.bgHeader
            border.color: theme.borderSubtle
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 8

                Button {
                    text: "监听与错误诊断 (" + controller.listenersModel.count + ")"
                    implicitHeight: 28
                    onClicked: root.activeTab = 0
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: 12
                        font.bold: root.activeTab === 0
                        color: root.activeTab === 0 ? theme.accent : theme.textSecondary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        radius: 5
                        color: root.activeTab === 0 ? theme.bgSelected : "transparent"
                    }
                }

                Button {
                    text: "运行日志"
                    implicitHeight: 28
                    onClicked: root.activeTab = 1
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: 12
                        font.bold: root.activeTab === 1
                        color: root.activeTab === 1 ? theme.accent : theme.textSecondary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        radius: 5
                        color: root.activeTab === 1 ? theme.bgSelected : "transparent"
                    }
                }

                Item { Layout.fillWidth: true }

                StatChip { label: "定时器"; value: controller.timerMode }
                StatChip { label: "总TX/s"; value: Number(controller.totals.tx_rate || 0).toFixed(1); valueColor: theme.success }
                StatChip { label: "在途"; value: (controller.totals.queued_packets || 0) + "p"; valueColor: theme.accent }
                StatChip { label: "未匹配"; value: String(controller.totals.unmatched_packets || 0); valueColor: (controller.totals.unmatched_packets || 0) > 0 ? theme.warning : theme.textPrimary }
                StatChip { label: "WSA10054"; value: String(controller.totals.wsa10054 || 0); valueColor: (controller.totals.wsa10054 || 0) > 0 ? theme.warning : theme.textPrimary }
                StatChip { label: "溢出"; value: String(controller.totals.overflow_drops || 0); valueColor: (controller.totals.overflow_drops || 0) > 0 ? theme.danger : theme.textPrimary }
                StatChip { label: "重启丢弃"; value: String(controller.lastDiscardedPending) }
            }
        }

        // Tab 0: Listeners Diagnostics Table
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.activeTab === 0
            spacing: 0

            Rectangle {
                Layout.fillWidth: true
                height: 28
                color: theme.bgSubtle
                border.color: theme.borderSubtle
                border.width: 1

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    Text { text: "监听 Socket"; Layout.preferredWidth: 180; font.pixelSize: 11; font.bold: true; color: theme.textSecondary }
                    Text { text: "未匹配包数"; Layout.preferredWidth: 110; font.pixelSize: 11; font.bold: true; color: theme.textSecondary; horizontalAlignment: Text.AlignRight }
                    Text { text: "最近未匹配对端 (Peer)"; Layout.fillWidth: true; font.pixelSize: 11; font.bold: true; color: theme.textSecondary; leftPadding: 16 }
                    Text { text: "WSA10054"; Layout.preferredWidth: 100; font.pixelSize: 11; font.bold: true; color: theme.textSecondary; horizontalAlignment: Text.AlignRight }
                    Text { text: "接收错误"; Layout.preferredWidth: 90; font.pixelSize: 11; font.bold: true; color: theme.textSecondary; horizontalAlignment: Text.AlignRight }
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: controller.listenersModel
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    width: ListView.view.width
                    height: 28
                    color: index % 2 === 0 ? theme.bgSurface : theme.bgSubtle

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        Text { text: listen; Layout.preferredWidth: 180; font.pixelSize: 12; font.family: "Consolas"; color: theme.textPrimary }
                        Text { text: unmatched; Layout.preferredWidth: 110; font.pixelSize: 12; font.family: "Consolas"; color: unmatched > 0 ? theme.warning : theme.textSecondary; horizontalAlignment: Text.AlignRight }
                        Text { text: lastUnmatchedPeer; Layout.fillWidth: true; font.pixelSize: 12; font.family: "Consolas"; color: lastUnmatchedPeer !== "-" ? theme.warning : theme.textMuted; leftPadding: 16 }
                        Text { text: wsa10054; Layout.preferredWidth: 100; font.pixelSize: 12; font.family: "Consolas"; color: wsa10054 > 0 ? theme.warning : theme.textSecondary; horizontalAlignment: Text.AlignRight }
                        Text { text: recvErrors; Layout.preferredWidth: 90; font.pixelSize: 12; font.family: "Consolas"; color: recvErrors > 0 ? theme.danger : theme.textSecondary; horizontalAlignment: Text.AlignRight }
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: controller.listenersModel.count === 0
                    text: "启动引擎后显示各监听端口实时诊断（每 250ms 刷新）"
                    font.pixelSize: 12
                    color: theme.textMuted
                }
            }
        }

        // Tab 1: Event Logs
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.activeTab === 1
            spacing: 0

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                TextArea {
                    id: logArea
                    readOnly: true
                    selectByMouse: true
                    text: controller.logText
                    font.pixelSize: 11
                    font.family: "Consolas"
                    color: theme.textPrimary
                    background: Rectangle { color: theme.bgSurface }
                    wrapMode: TextArea.WrapAnywhere
                }
            }
        }
    }
}
