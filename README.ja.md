# KM003C FW Extensions

[English](README.md) · 日本語

ChargerLAB POWER-Z KM003Cの純正ファームウェアへ機能を追加する実験的な拡張集です。**QR表示・転送版**と**画面キャプチャ版**を、純正FWごとの対応情報と共通ソースで管理します。

**対象は既知の純正FW 2.0.7です。** キャプチャ版はHW 2.1（ROM 4MB）とHW 2.3、QR版はHW 2.3に対応します。[対応表](docs/COMPATIBILITY.ja.md)を確認してください。

## 版を選ぶ

| 版 | 機能 | 本体操作 |
| --- | --- | --- |
| `qr` | 電源のSPR/EPR PDO、ケーブルe-marker、PPS StatusをQRへ出力しスマホへ取り込む | 左右を約1秒長押し。左右でQR切替、Exitで戻る |
| `screen` | 通常240×240とスクロール全体の縦長BMPを保存。起動番号＋メニュー名＋撮影番号でUSBから取り出す | 左右を0.5〜2秒未満押して離すと通常撮影、2秒以上で縦長撮影 |

**本体へ入れるファームウェアは別々です。** リポジトリをまとめても、本体上でQRとキャプチャを同時には有効にしません。

キャプチャの実保存は、HW 2.3が**1472 KiB・上限96枚**、HW 2.1が**1 MiB・上限64枚**です。画像が大きければ先に容量が埋まります。USBに見える128 MiBはBMP展開用の仮想容量です。[キャプチャの操作仕様](docs/SCREEN-CAPTURE-207.ja.md)を参照してください。

新しい画像は `0001_MEASUREMENT02.BMP` のように起動ごとにまとまり、旧画像の名前は保持します。旧版や純正に戻す前に画像を退避し、本体に入っているキャプチャ版で保存画像を消去してください。

## Windowsへ導入

- **キャプチャ版（HW 2.1／2.3）**。Windows x64 ZIPを展開して `Install.cmd` を起動します。統合版v1から更新する場合は、メニュー2で元の純正バックアップを指定します。画面表示は英語で、英日手順書を同梱しています。[v0.3.2をダウンロード](https://github.com/inuchanbt/km003c-fw-extensions/releases/tag/v0.3.2-fw2.0.7) · [日本語手順書](docs/INSTALL-CAPTURE-TRIAL.ja.md)
- **QR版（HW 2.3）**。従来のWindows ZIPにある英日インストーラーを使います。[v0.3.1をダウンロード](https://github.com/inuchanbt/km003c-fw-extensions/releases/tag/v0.3.1-fw2.0.7) · [日本語手順書](docs/INSTALL.ja.md)

導入と復旧に必要な個体データは、元の純正バックアップからPC上で作ります。インストーラーは未署名です。

## ソースから作成

Python 3.12以上と、`arm-none-eabi`へ出力できるClang/LLDを使います。スマホ側の試験にはNode.js、更新ツールの作成にはRustが必要です。

```sh
python -m pip install -r requirements.txt
python tools/build_firmware.py --stock-fw 2.0.7 --variant qr --clang clang
python tools/build_firmware.py --stock-fw 2.0.7 --variant screen --clang clang
```

PowerShellでは `./Build.ps1 -Variant screen -Clang C:\tools\clang.exe` も使えます。

出力先は `artifacts/fw2.0.7/<variant>/` です。ここで生成するのは**純正ROMを含まない拡張部品で、そのまま本体へ書き込むファームウェアではありません**。導入には自分の個体の検証済みバックアップと専用ツールが必要です。[導入と復旧](docs/INSTALL.ja.md)を先に確認してください。上記のビルド・試験だけではUSBを操作しません。

## QR取込ページ

[互換QR取込ページを開く](https://inuchanbt.github.io/km003c-pd-interrogator/)。ブラウザー内でデコードし、明示された合成デモも試せます。実機確認済みのQR版との互換性を保つため既存URLを継続しています。ソースは `phone/` です。

```sh
python -m pdinfo demo --output artifacts/demo --qr
python -m pdinfo serve
```

詳細は[本体の取得・操作](docs/NATIVE-INFO-207.ja.md)と[ホストCLI](docs/HOST-CLI.md)を参照してください。

## 純正FWとプロジェクトのバージョン

キャプチャ版 **v0.3.2** は純正FW **2.0.7** に対応します。両機種でThemesの一覧を最後の `purple` まで撮影できました。HW 2.3は240×296のBMPをUSBから取得し、HW 2.1では [@tomoca2](https://github.com/tomoca2) さんから試験版の更新、縦長撮影、復旧の成功報告がありました。

HW 2.3の1台で0.3.1のキャプチャ部品を試し、Auto detectionの240×305 BMPをダイアログあり・なしの両方でUSBから取得しました。ダイアログとFW番号は各1回でした。以前の版では起動番号付きファイル名、48枚のUSBコピー、追加保存領域を確認済みです。Windows ZIPはオフラインで検証しています。[実機記録](docs/SCREEN-CAPTURE-BOOT-NUMBER.ja.md)

CIは公開ソースだけでPython、C/ARM、更新ツールを検証します。ROM/RAMや実機を使う試験の個体データは公開しません。[開発と移植](CONTRIBUTING.md)も参照してください。

## ライセンスと由来

自作部分は[MIT](LICENSE)です。第三者部分は各ライセンスを維持します。Nayuki QR生成器はMIT、jsQRはApache-2.0、別途準備する依存元にもそれぞれ条件があります。[第三者ライセンス一覧](THIRD_PARTY_NOTICES.md)を同梱しています。純正ファームウェアや個体データは同梱せず、MITへ変更もしません。

QR実装の由来は [km003c-pd-interrogator](https://github.com/inuchanbt/km003c-pd-interrogator) の `ecbeff2` です。出典を残して拡張集へまとめています。ChargerLAB公式のファームウェアではありません。
