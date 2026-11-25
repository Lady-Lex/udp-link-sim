# Code signing policy

Version 0.1.0 is unsigned. SHA256SUMS.txt checks file integrity; it is not a publisher signature. No signing service has endorsed this project.

Project: https://github.com/Lady-Lex/udp-link-sim. Windows x64 artifacts are published in GitHub Releases. The MIT license covers original project code; third-party components retain their own licenses.

Proposed signing scope: only UdpLinkSim.exe built from reviewed, tagged source and project-controlled build scripts. The repository owner reviews and approves signing. Before a signed release, verify the Authenticode chain and timestamp, compute the final SHA-256 after signing and publish it alongside the executable. Keep prior release assets unchanged.
