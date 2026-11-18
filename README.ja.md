# KM003C FW Extensions

[English](README.md) · 日本語

ChargerLAB POWER-Z KM003Cの純正ファームウェアへ機能を追加する実験的な拡張集です。**QR表示・転送版**と**画面キャプチャ版**を、純正FWごとの対応情報と共通ソースで管理します。

**現在の対象は純正FW 2.0.7／HW 2.3の既知ハッシュだけです。** バージョン表示が同じでも導入可能とは限りません。[対応表](docs/COMPATIBILITY.ja.md)と[プロファイル](firmware/v2.0.7/profile.json)を確認してください。

## 版を選ぶ

| 版 | 機能 | 本体操作 |
| --- | --- | --- |
| `qr` | 電源のSPR/EPR PDO、ケーブルe-marker、PPS StatusをQRへ出力しスマホへ取り込む | 左右を約1秒長押し。左右でQR切替、Exitで戻る |
| `screen` | 通常240×240とスクロール全体の縦長BMPを保存。起動番号＋メニュー名＋撮影番号でUSBから取り出す | 左右を0.5〜2秒未満押して離すと通常撮影、2秒以上で縦長撮影 |

**本体へ入れるファームウェアは別々です。** リポジトリをまとめても、本体上でQRとキャプチャを同時には有効にしません。

キャプチャの実保存は**1472 KiB・管理上限96枚**です。画像が大きければ先に容量が埋まります。USBに見える128 MiBはBMP展開用の仮想容量です。[キャプチャの操作仕様](docs/SCREEN-CAPTURE-207.ja.md)を参照してください。

新しい画像は `0001_MEASUREMENT02.BMP` のように起動ごとにまとまり、旧画像の名前は保持します。**旧キャプチャ版は新形式を読めないため、旧版や純正に戻す前に画像を退避し、この版で両保存バンクを消去してください。**

## Windowsへ導入

[Releases](https://github.com/inuchanbt/km003c-fw-extensions/releases)の**Windows x64 ZIP**を展開し、**Install.cmdをダブルクリック**します。英日メニューで、自分の本体の純正バックアップ、BOOT Loaderでの読取確認、QR／キャプチャの準備、導入、純正復元を進められます。Python・Rust・コンパイラーは不要です。純正FWや個体の復旧データはZIPへ入れず、本体のバックアップからPC上で作ります。[導入手順](docs/INSTALL.ja.md)を先に確認してください。実験版・未署名で、[検証範囲](docs/WINDOWS-RELEASE.md)を記載しています。

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

プロジェクトは **0.3.1**、対応する純正FWは **2.0.7** です。タグは `v0.3.1-fw2.0.7` のように両方を示します。別の純正FWに対応するには、`firmware/v<純正FW>/` に専用のアドレス・ハッシュ・試験を用意します。

HW 2.3の1台で0.3.1のキャプチャ部品を試し、Auto detectionの240×305 BMPをダイアログあり・なしの両方でUSBから取得しました。ダイアログとFW番号は各1回でした。以前の版では起動番号付きファイル名、48枚のUSBコピー、追加保存領域を確認済みです。Windows ZIPはオフラインで検証しています。[実機記録](docs/SCREEN-CAPTURE-BOOT-NUMBER.ja.md)

CIは公開ソースだけでPython、C/ARM、更新ツールを検証します。ROM/RAMや実機を使う試験の個体データは公開しません。[開発と移植](CONTRIBUTING.md)も参照してください。

## ライセンスと由来

自作部分は[MIT](LICENSE)です。第三者部分は各ライセンスを維持します。Nayuki QR生成器はMIT、jsQRはApache-2.0、別途準備する依存元にもそれぞれ条件があります。[第三者ライセンス一覧](THIRD_PARTY_NOTICES.md)を同梱しています。純正ファームウェアや個体データは同梱せず、MITへ変更もしません。

QR実装の由来は [km003c-pd-interrogator](https://github.com/inuchanbt/km003c-pd-interrogator) の `ecbeff2` です。出典を残して拡張集へまとめています。ChargerLAB公式のファームウェアではありません。
