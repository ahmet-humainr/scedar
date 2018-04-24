import numpy as np
import scipy.spatial as spspatial
import scipy.stats as spstats
from abc import ABC, abstractmethod


def npfloat_1d(x, dtype=np.dtype("f8")):
    """Convert x to 1d np float array
    Args:
        x (1d sequence of values convertable to np.float)
        dtype (np float type): default to 64-bit float

    Returns:
        xarr (1d np.float array)

    Raises:
        ValueError: If x is not convertable to np.float or non-1d. If dtype is
        not subdtype of np number.
    """
    if not np.issubdtype(dtype, np.number):
        raise ValueError("dtype must be a type of numpy number")

    xarr = np.array(x, dtype=dtype)
    if xarr.ndim != 1:
        raise ValueError("x should be 1D array. "
                         "x.shape: {}".format(xarr.shape))
    return xarr


class Mdl(ABC):
    """Minimum description length abstract base class

    Attributes:
        _x (1D np.float array): data used for fit mdl
        _n (np.int): number of points in x
    """
    @abstractmethod
    def __init__(self, x):
        """Initialize
        Args:
            x (1D np.float array): data used for fit mdl
        """
        self._x = npfloat_1d(x)
        # avoid divide by 0 exception
        self._n = np.int_(self._x.shape[0])

    @abstractmethod
    def encode(self, x):
        """Encode another 1D float array with fitted code
        Args:
            x (1D np.float array): data to encode
        """
        raise NotImplementedError

    @property
    def x(self):
        return self._x.copy()

    @property
    @abstractmethod
    def mdl(self):
        raise NotImplementedError


class MultinomialMdl(Mdl):
    """
    Encode discrete values using multinomial distribution

    Args:
        x (1d float array): Should be non-negative

    Note:
        When x only has 1 uniq value. Encode the the number of values only.
    """

    def __init__(self, x):
        super().__init__(x)

        uniq_vals, uniq_val_cnts = np.unique(x, return_counts=True)
        self._n_uniq = len(uniq_vals)
        self._uniq_vals = uniq_vals
        self._uniq_val_cnts = uniq_val_cnts
        # make division by 0 valid.
        self._uniq_val_ps = uniq_val_cnts / self._n
        # create a lut for unique vals and ps
        self._uniq_val_p_lut = dict(zip(uniq_vals, self._uniq_val_ps))

        if len(self._uniq_vals) > 1:
            mdl = (-np.log(self._uniq_val_ps) * self._uniq_val_cnts).sum()
        elif len(self._uniq_vals) == 1:
            mdl = np.log(self._n)
        else:
            # len(x) == 0
            mdl = 0

        self._mdl = mdl
        return

    def encode(self, qx, use_adjescent_when_absent=False):
        """Encode another 1D float array with fitted code

        Args:
            qx (1d float array): query data
            use_adjescent_when_absent (bool): whether to use adjascent value
                to compute query mdl. If not, uniform mdl is used. If
                adjascent values have same distance to query value, choose the
                one with smaller mdl.

        Returns:
            qmdl (float)
        """
        qx = npfloat_1d(qx)
        if qx.size == 0:
            return 0

        # Encode with 32bit float
        unif_q_val_mdl = np.log(np.max(np.abs(qx)*2))
        if self._n == 0:
            # uniform
            return qx.size * unif_q_val_mdl

        q_uniq_vals, q_uniq_val_cnts = np.unique(qx, return_counts=True)
        q_mdl = 0
        for uval, ucnt in zip(q_uniq_vals, q_uniq_val_cnts):
            uval_p = self._uniq_val_p_lut.get(uval)
            if uval_p is None:
                if use_adjescent_when_absent:
                    uind = np.searchsorted(self._uniq_vals, uval)
                    if uind <= 0:
                        # uval lower than minimum
                        uval_p = self._uniq_val_ps[0]
                    elif uind >= self._n_uniq:
                        # uval higher than maximum
                        uval_p = self._uniq_val_ps[-1]
                    else:
                        # uval within range [1, _n_uniq-1]
                        # abs diff between uval and left val
                        l_diff = np.abs(self._uniq_vals[uind-1] - uval)
                        # abs diff between uval and right avl
                        r_diff = np.abs(self._uniq_vals[uind] - uval)
                        if l_diff < r_diff:
                            # closer to left
                            uval_p = self._uniq_val_ps[uind-1]
                        elif l_diff > r_diff:
                            # closer to right
                            uval_p = self._uniq_val_ps[uind]
                        else:
                            # same distance, choose max p
                            uval_p = max(self._uniq_val_ps[uind-1],
                                         self._uniq_val_ps[uind])
                    uval_mdl = -np.log(uval_p)
                else:
                    uval_mdl = unif_q_val_mdl
            else:
                uval_mdl = -np.log(uval_p)
            q_mdl += uval_mdl * ucnt
        return q_mdl

    @property
    def mdl(self):
        return self._mdl


class GKdeMdl(object):
    """docstring for GKdeMdl"""

    def __init__(self, x, kde_bw_method="silverman"):
        super(GKdeMdl, self).__init__()

        if x.ndim != 1:
            raise ValueError("x should be 1D array. "
                             "x.shape: {}".format(x.shape))

        self._x = x
        self._n = x.shape[0]

        self._bw_method = kde_bw_method

        self._mdl = self._kde_mdl()

    def _kde_mdl(self):
        if self._n == 0:
            kde = None
            logdens = None
            bw_factor = None
            # no non-zery vals. Indicator encoded by zi mdl.
            kde_mdl = 0
        else:
            try:
                logdens, kde = self.gaussian_kde_logdens(
                    self._x, bandwidth_method=self._bw_method,
                    ret_kernel=True)
                kde_mdl = -logdens.sum() + np.log(2)
                bw_factor = kde.factor
            except Exception as e:
                kde = None
                logdens = None
                bw_factor = None
                # encode just single value or multiple values
                kde_mdl = MultinomialMdl(
                    (self._x * 100).astype(int)).mdl

        self._bw_factor = bw_factor
        self._kde = kde
        self._logdens = logdens
        return kde_mdl

    @property
    def bandwidth(self):
        if self._bw_factor is None:
            return None
        else:
            return self._bw_factor * self._x.std(ddof=1)

    @property
    def mdl(self):
        return self._mdl

    @property
    def x(self):
        return self._x.copy()

    @property
    def kde(self):
        return self._kde

    @staticmethod
    def gaussian_kde_logdens(x, bandwidth_method="silverman",
                             ret_kernel=False):
        """
        Estimate Gaussian kernel density estimation bandwidth for input `x`.

        Parameters
        ----------
        x: float array of shape `(n_samples)` or `(n_samples, n_features)`
            Data points for KDE estimation.
        bandwidth_method: string
            KDE bandwidth estimation method bing passed to
            `scipy.stats.gaussian_kde`.

        """

        # This package uses (n_samples, n_features) convention
        # scipy uses (n_featues, n_samples) convention
        # so it is necessary to reshape the data
        if x.ndim == 1:
            x = x.reshape(1, -1)
        elif x.ndim == 2:
            x = x.T
        else:
            raise ValueError("x should be 1/2D array. "
                             "x.shape: {}".format(x.shape))

        kde = spstats.gaussian_kde(x, bw_method=bandwidth_method)
        logdens = np.log(kde.evaluate(x))

        if ret_kernel:
            return (logdens, kde)
        else:
            return logdens


class ZeroIGKdeMdl(object):
    """
    Zero indicator Gaussian KDE MDL

    Encode the 0s and non-0s using bernoulli distribution.
    Then, encode non-0s using gaussian kde. Finally, one ternary val indicates
    all 0s, all non-0s, or otherwise


    Parameters
    ----------
    x: 1d float array
        Should be non-negative
    bandwidth_method: string
        KDE bandwidth estimation method bing passed to
        `scipy.stats.gaussian_kde`.
        Types:
        * `"scott"`: Scott's rule of thumb.
        * `"silverman"`: Silverman"s rule of thumb.
        * `constant`: constant will be timed by x.std(ddof=1) internally,
        because scipy times bw_method value by std. "Scipy weights its
        bandwidth by the ovariance of the input data" [3].
        * `callable`: scipy calls the function on self

    References
    ----------
    [1] https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.gaussian_kde.html

    [2] https://en.wikipedia.org/wiki/Kernel_density_estimation

    [3] https://jakevdp.github.io/blog/2013/12/01/kernel-density-estimation/

    [4] https://github.com/scipy/scipy/blob/v1.0.0/scipy/stats/kde.py#L42-L564

    """  # noqa

    def __init__(self, x, kde_bw_method="silverman"):
        super(ZeroIGKdeMdl, self).__init__()

        if x.ndim != 1:
            raise ValueError("x should be 1D array. "
                             "x.shape: {}".format(x.shape))

        self._x = x
        self._n = x.shape[0]

        self._x_nonzero = x[np.nonzero(x)]
        self._k = self._x_nonzero.shape[0]

        self._bw_method = kde_bw_method

        self._zi_mdl = self._compute_zero_indicator_mdl()
        self._kde_mdl_obj = GKdeMdl(self._x_nonzero, kde_bw_method)
        self._kde_mdl = self._kde_mdl_obj.mdl
        self._mdl = self._zi_mdl + self._kde_mdl

    def _compute_zero_indicator_mdl(self):
        if self._n == 0:
            zi_mdl = 0
        elif self._k == self._n or self._k == 0:
            zi_mdl = np.log(3)
        else:
            p = self._k / self._n
            zi_mdl = (np.log(3) - self._k * np.log(p) -
                      (self._n - self._k) * np.log(1-p))
        return zi_mdl

    @property
    def bandwidth(self):
        return self._kde_mdl_obj.bandwidth

    @property
    def kde(self):
        return self._kde_mdl_obj.kde

    @property
    def zi_mdl(self):
        return self._zi_mdl

    @property
    def kde_mdl(self):
        return self._kde_mdl

    @property
    def mdl(self):
        return self._mdl

    @property
    def x(self):
        return self._x.copy()

    @property
    def x_nonzero(self):
        return self._x_nonzero.copy()
