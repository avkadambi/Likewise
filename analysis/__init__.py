"""Analysis, validation and reporting. Not part of the served engine.

Three jobs, none of which belongs in a container that must stay small and make no
outbound call:

1. `crossvalidate` re-derives every statistic the engine computes, using SciPy,
   statsmodels and NumPy, and asserts the two agree to a stated tolerance. Where a
   reference implementation exists it is used; where one does not, the reference is a
   brute-force computation that is obviously correct and far too slow to ship.
2. `simulate` establishes the operating characteristics that no amount of unit testing
   can: the type-I error rate of the pooled test under a true null, its power as a
   function of effect size and stratum count, and the coverage of the interval.
3. `figures` produces the exhibits for the analysis report from the real snapshot.

Nothing here is imported by `likewise/`, and a test asserts it.
"""
