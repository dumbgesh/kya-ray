# Token Pricing and Workload Estimation

For Kya-Ray, each request will usually contain a short selected passage, a system prompt, and a relatively short answer. That is a favorable workload for token-based APIs.

The cost is:
\[
\text{Cost} =
\frac{I \times P_i + O \times P_o}{1{,}000{,}000}
\]

Where \(I\) is input tokens, \(O\) is output tokens, and \(P_i\) and \(P_o\) are the provider's respective prices per million tokens.

