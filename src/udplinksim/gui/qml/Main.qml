import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: win
    visible: true
    width: 1360
    height: 840
    minimumWidth: 1024
    minimumHeight: 640
    title: appController.appTitle + (appController.hasUnsavedChanges ? " *" : "")
    color: appTheme.bgApp

    Theme {
        id: appTheme
        dark: appController.darkMode
    }

    FileDialog {
        id: openDialog
        title: "导入 UDP 规则 CSV 文件"
        nameFilters: ["CSV 配置文件 (*.csv)", "所有文件 (*)"]
        fileMode: FileDialog.OpenFile
        onAccepted: appController.importCsv(selectedFile)
    }

    FileDialog {
        id: saveAsDialog
        title: "另存为 UDP 规则 CSV 文件"
        nameFilters: ["CSV 配置文件 (*.csv)", "所有文件 (*)"]
        fileMode: FileDialog.SaveFile
        defaultSuffix: "csv"
        onAccepted: appController.saveCsvAs(selectedFile)
    }

    component ToolbarButton: Button {
        property bool primary: false
        property bool dangerStyle: false
        implicitHeight: 32
        leftPadding: 12
        rightPadding: 12
        contentItem: Text {
            text: parent.text
            font.pixelSize: 12
            font.bold: parent.primary
            color: !parent.enabled ? appTheme.textMuted
                 : parent.primary ? appTheme.accentText
                 : parent.dangerStyle ? appTheme.danger
                 : appTheme.textPrimary
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 6
            color: !parent.enabled ? appTheme.bgSubtle
                 : parent.primary ? (parent.hovered ? appTheme.accentHover : appTheme.accent)
                 : parent.dangerStyle ? (parent.hovered ? appTheme.dangerBg : appTheme.bgSurface)
                 : (parent.hovered ? appTheme.bgHover : appTheme.bgSurface)
            border.color: parent.primary ? "transparent"
                        : parent.dangerStyle ? appTheme.danger
                        : appTheme.border
            border.width: 1
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        // Top Toolbar + Config Path & Status Header
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: headerCol.implicitHeight + 16
            color: appTheme.bgSurface
            border.color: appTheme.border
            border.width: 1
            radius: 8

            ColumnLayout {
                id: headerCol
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: appController.appTitle
                        font.pixelSize: 16
                        font.bold: true
                        color: appTheme.textPrimary
                    }

                    // Engine status pill
                    Rectangle {
                        radius: 11
                        implicitHeight: 22
                        implicitWidth: statusLbl.implicitWidth + 16
                        color: appController.engineState === "running" ? appTheme.successBg
                             : appController.engineState === "error" ? appTheme.dangerBg
                             : appTheme.bgSubtle
                        border.color: appController.engineState === "running" ? appTheme.success
                                    : appController.engineState === "error" ? appTheme.danger
                                    : appTheme.border
                        Text {
                            id: statusLbl
                            anchors.centerIn: parent
                            text: appController.engineStatusText
                            font.pixelSize: 11
                            font.bold: true
                            color: appController.engineState === "running" ? appTheme.success
                                 : appController.engineState === "error" ? appTheme.danger
                                 : appTheme.textSecondary
                        }
                    }

                    // Unsaved pill
                    Rectangle {
                        visible: appController.hasUnsavedChanges
                        radius: 11
                        implicitHeight: 22
                        implicitWidth: unsavedLbl.implicitWidth + 14
                        color: appTheme.warningBg
                        border.color: appTheme.warning
                        Text {
                            id: unsavedLbl
                            anchors.centerIn: parent
                            text: "未保存"
                            font.pixelSize: 11
                            font.bold: true
                            color: appTheme.warning
                        }
                    }

                    // Pending apply pill
                    Rectangle {
                        visible: appController.hasPendingApply
                        radius: 11
                        implicitHeight: 22
                        implicitWidth: pendingLbl.implicitWidth + 14
                        color: appTheme.warningBg
                        border.color: appTheme.warning
                        Text {
                            id: pendingLbl
                            anchors.centerIn: parent
                            text: "待应用 (需重启引擎)"
                            font.pixelSize: 11
                            font.bold: true
                            color: appTheme.warning
                        }
                    }

                    Item { Layout.fillWidth: true }

                    ToolbarButton {
                        text: appController.darkMode ? "☀ 浅色模式" : "☾ 深色模式"
                        onClicked: appController.toggleTheme()
                    }
                }

                // Second row: config path + actions
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 32
                        radius: 6
                        color: appTheme.bgSubtle
                        border.color: appTheme.borderSubtle

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            Text {
                                text: "配置文件:"
                                font.pixelSize: 11
                                color: appTheme.textSecondary
                            }
                            Text {
                                Layout.fillWidth: true
                                text: appController.configPath !== "" ? appController.configPath : "未关联文件 (新建配置)"
                                font.pixelSize: 11
                                font.family: "Consolas"
                                color: appTheme.textPrimary
                                elide: Text.ElideMiddle
                            }
                        }
                    }

                    ToolbarButton { text: "导入 CSV"; onClicked: openDialog.open() }
                    ToolbarButton {
                        text: "保存"
                        enabled: appController.isValid
                        onClicked: {
                            if (appController.configPath === "") saveAsDialog.open()
                            else appController.saveCsv()
                        }
                    }
                    ToolbarButton {
                        text: "另存为"
                        enabled: appController.isValid
                        onClicked: saveAsDialog.open()
                    }

                    Rectangle { width: 1; height: 22; color: appTheme.border }

                    ToolbarButton { text: "+ 新增"; onClicked: appController.addRule() }
                    ToolbarButton {
                        text: "复制"
                        enabled: appController.selectedIndex >= 0
                        onClicked: appController.duplicateRule(appController.selectedIndex)
                    }
                    ToolbarButton {
                        text: "删除"
                        enabled: appController.selectedIndex >= 0
                        onClicked: appController.deleteRule(appController.selectedIndex)
                    }

                    Rectangle { width: 1; height: 22; color: appTheme.border }

                    ToolbarButton {
                        primary: true
                        text: appController.engineRunning
                              ? (appController.hasPendingApply ? "应用并重启引擎" : "重启引擎")
                              : "启动引擎"
                        enabled: appController.isValid
                        onClicked: appController.applyAndRestart()
                    }
                    ToolbarButton {
                        dangerStyle: true
                        text: "停止"
                        enabled: appController.engineRunning
                        onClicked: appController.stopEngine()
                    }
                    ToolbarButton {
                        text: "清零统计"
                        enabled: appController.engineRunning
                        onClicked: appController.resetStats()
                    }
                }
            }
        }

        // Main SplitView: Top (RuleTable + PropertyPane) / Bottom (DiagnosticsPane)
        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Vertical

            SplitView {
                SplitView.fillHeight: true
                SplitView.minimumHeight: 280
                orientation: Qt.Horizontal

                RuleTable {
                    SplitView.fillWidth: true
                    SplitView.minimumWidth: 640
                    theme: appTheme
                    controller: appController
                }

                PropertyPane {
                    SplitView.preferredWidth: 340
                    SplitView.minimumWidth: 290
                    SplitView.maximumWidth: 460
                    theme: appTheme
                    controller: appController
                }
            }

            DiagnosticsPane {
                SplitView.preferredHeight: 205
                SplitView.minimumHeight: 140
                theme: appTheme
                controller: appController
            }
        }
    }
}
