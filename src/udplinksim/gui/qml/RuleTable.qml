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

    readonly property var columns: [
        { title: "#", width: 34, align: Text.AlignHCenter },
        { title: "监听端点 (Listen)", width: 142, align: Text.AlignLeft },
        { title: "来源匹配 (Source)", width: 142, align: Text.AlignLeft },
        { title: "固定目标 (Target)", width: 142, align: Text.AlignLeft },
        { title: "延迟(ms)", width: 68, align: Text.AlignRight },
        { title: "抖动σ", width: 58, align: Text.AlignRight },
        { title: "丢包%", width: 54, align: Text.AlignRight },
        { title: "RX", width: 72, align: Text.AlignRight },
        { title: "TX", width: 72, align: Text.AlignRight },
        { title: "TX/s", width: 64, align: Text.AlignRight },
        { title: "队列(包/B)", width: 92, align: Text.AlignRight },
        { title: "主动丢包", width: 66, align: Text.AlignRight },
        { title: "溢出", width: 54, align: Text.AlignRight },
        { title: "错误", width: 52, align: Text.AlignRight }
    ]

    readonly property int totalWidth: {
        let w = 16
        for (let i = 0; i < columns.length; i++) w += columns[i].width
        return w
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Table title bar
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
                    text: "实时转发规则表 (" + controller.rulesModel.count + " 条)"
                    font.pixelSize: 13
                    font.bold: true
                    color: theme.textPrimary
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: "每行单向 · 同监听共享 Socket · 精确优先于通配端口 0"
                    font.pixelSize: 11
                    color: theme.textSecondary
                }
            }
        }

        // Horizontally scrollable table area
        Flickable {
            id: hFlick
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: Math.max(width, root.totalWidth)
            contentHeight: height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

            ColumnLayout {
                width: hFlick.contentWidth
                height: hFlick.height
                spacing: 0

                // Column Header
                Rectangle {
                    Layout.fillWidth: true
                    height: 32
                    color: theme.bgSubtle
                    border.color: theme.borderSubtle
                    border.width: 1

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        Repeater {
                            model: root.columns
                            delegate: Text {
                                width: modelData.width
                                height: 32
                                text: modelData.title
                                horizontalAlignment: modelData.align
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 11
                                font.bold: true
                                color: theme.textSecondary
                                elide: Text.ElideRight
                                rightPadding: 6
                            }
                        }
                    }
                }

                // Rows ListView
                ListView {
                    id: listView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: controller.rulesModel
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        id: rowItem
                        width: listView.width
                        height: 34
                        readonly property bool isSelected: index === controller.selectedIndex
                        readonly property bool hasErr: errorText !== ""

                        color: hasErr ? theme.dangerBg
                             : isSelected ? theme.bgSelected
                             : (mouseArea.containsMouse ? theme.bgHover
                                : (index % 2 === 0 ? theme.bgSurface : theme.bgSubtle))

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: theme.borderSubtle
                        }

                        MouseArea {
                            id: mouseArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: controller.selectedIndex = index
                        }

                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8

                            Text {
                                width: root.columns[0].width; height: 34
                                text: rowIndex
                                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.bold: isSelected
                                color: hasErr ? theme.danger : theme.textSecondary
                                rightPadding: 6
                            }
                            Text {
                                width: root.columns[1].width; height: 34
                                text: listenIp + ":" + listenPort
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: theme.textPrimary; elide: Text.ElideRight; rightPadding: 6
                            }
                            Text {
                                width: root.columns[2].width; height: 34
                                text: sourceIp + ":" + (sourcePort === "0" ? "* (0)" : sourcePort)
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: sourcePort === "0" ? theme.accent : theme.textPrimary
                                elide: Text.ElideRight; rightPadding: 6
                            }
                            Text {
                                width: root.columns[3].width; height: 34
                                text: targetIp + ":" + targetPort
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: theme.textPrimary; elide: Text.ElideRight; rightPadding: 6
                            }
                            Text {
                                width: root.columns[4].width; height: 34
                                text: baseMs
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: theme.textPrimary; rightPadding: 6
                            }
                            Text {
                                width: root.columns[5].width; height: 34
                                text: sigmaMs
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: theme.textPrimary; rightPadding: 6
                            }
                            Text {
                                width: root.columns[6].width; height: 34
                                text: lossPct + "%"
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: Number(lossPct) > 0 ? theme.warning : theme.textSecondary
                                rightPadding: 6
                            }
                            Text {
                                width: root.columns[7].width; height: 34
                                text: rx
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: theme.textPrimary; rightPadding: 6
                            }
                            Text {
                                width: root.columns[8].width; height: 34
                                text: tx
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: theme.success; rightPadding: 6
                            }
                            Text {
                                width: root.columns[9].width; height: 34
                                text: txRate.toFixed(1)
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: theme.textPrimary; rightPadding: 6
                            }
                            Text {
                                width: root.columns[10].width; height: 34
                                text: queuedPackets + " / " + queuedBytes
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 11; font.family: "Consolas"
                                color: queuedPackets > 0 ? theme.accent : theme.textSecondary
                                rightPadding: 6
                            }
                            Text {
                                width: root.columns[11].width; height: 34
                                text: lossDrops
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: lossDrops > 0 ? theme.warning : theme.textMuted
                                rightPadding: 6
                            }
                            Text {
                                width: root.columns[12].width; height: 34
                                text: overflowDrops
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: overflowDrops > 0 ? theme.danger : theme.textMuted
                                rightPadding: 6
                            }
                            Text {
                                width: root.columns[13].width; height: 34
                                text: sendErrors
                                horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 12; font.family: "Consolas"
                                color: sendErrors > 0 ? theme.danger : theme.textMuted
                                rightPadding: 6
                            }
                        }
                    }

                    // Empty state
                    Label {
                        anchors.centerIn: parent
                        visible: controller.rulesModel.count === 0
                        text: "暂无转发规则\n请点击顶部「导入 CSV」或「新增规则」"
                        horizontalAlignment: Text.AlignHCenter
                        font.pixelSize: 13
                        color: theme.textSecondary
                    }
                }
            }
        }
    }
}
